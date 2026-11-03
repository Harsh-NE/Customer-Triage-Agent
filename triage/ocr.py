"""
ocr.py -- read the text in a screenshot a customer attaches (an error dialog, a terminal, a Docker Desktop window).

Started from the resolver track's version (Tesseract, a pre-processing step, and `extract_error_context`); this version adds what an
upload endpoint needs: the file is checked before it is decoded, the result says how confident the read was, a missing engine is
a normal answer ("could not read this") rather than a crash, and secrets are masked in the text before it goes anywhere.

Engines, tried in this order (OCR_ENGINE=tesseract|rapidocr forces one):
  1. Tesseract via pytesseract. It needs the Tesseract PROGRAM installed: on Windows https://github.com/UB-Mannheim/tesseract/wiki,
     found on PATH, in the usual install folders, or at TESSERACT_CMD.
  2. rapidocr-onnxruntime: pure pip, no separate program.

The text that comes back is UNTRUSTED customer input like anything else they type: it is shown to the customer to correct, it goes through
the same guardrails and the Clarifier, and it is never an instruction. Nothing here sends the image anywhere.
"""

from __future__ import annotations

import io
import logging
import os
import re
import shutil
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional, Union

from PIL import Image, ImageEnhance, ImageFilter

log = logging.getLogger(__name__)

ALLOWED_FORMATS = {"PNG": "png", "JPEG": "jpg", "BMP": "bmp", "TIFF": "tiff", "WEBP": "webp"}
MAX_BYTES = 5 * 1024 * 1024
MAX_SIDE = 6000                    # pixels; a larger image is refused before it is decoded in full
MAX_TEXT_CHARS = 4000
LOW_CONFIDENCE = 0.5               # below this the text is shown with "this may be wrong; please check it"
Image.MAX_IMAGE_PIXELS = MAX_SIDE * MAX_SIDE

_TESSERACT_PATHS = [r"C:\Program Files\Tesseract-OCR\tesseract.exe", r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"]
_SECRETS = [
    (re.compile(r"\b(?:ghp|gho|github_pat|sk|xox[abp]|AKIA)[A-Za-z0-9_\-]{12,}\b"), "<TOKEN>"),
    (re.compile(r"(?i)\b(password|passwd|pwd|token|secret|api[_-]?key)\s*[:=]\s*\S+"), r"\1=<REDACTED>"),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{16,}"), "Bearer <REDACTED>"),
    # `docker login -u me -p hunter2`: only on a login line, because `docker run -p 8080:80` is a port, not a password
    (re.compile(r"(?i)(docker\s+login\b[^\n]*?\s(?:-p|--password)[ =])\S+"), r"\1<REDACTED>"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "<EMAIL>"),
]


class OcrError(ValueError):
    """The upload is not something we will read (wrong type, too big, not an image). The message is safe to show the customer."""


@dataclass
class OcrResult:
    ok: bool                                       # some text was read
    text: str = ""
    confidence: Optional[float] = None             # 0..1, mean word confidence; None when the engine does not say
    engine: Optional[str] = None
    reason: Optional[str] = None                   # why nothing was read: no_engine | no_text | engine_error
    latency_ms: float = 0.0
    error_messages: list[str] = field(default_factory=list)
    exit_codes: list[str] = field(default_factory=list)

    @property
    def low_confidence(self) -> bool:
        return self.ok and self.confidence is not None and self.confidence < LOW_CONFIDENCE

    def to_dict(self) -> dict:
        return {**asdict(self), "low_confidence": self.low_confidence}


# ---------------------------------------------------------------- input checks

def validate_image(data: bytes) -> tuple[Image.Image, str]:
    """Check size, real format and dimensions, and return (image, file extension). Raises OcrError with a customer-safe message."""
    if not data:
        raise OcrError("The file is empty.")
    if len(data) > MAX_BYTES:
        raise OcrError(f"The image is larger than {MAX_BYTES // (1024 * 1024)} MB. Please crop it or send a smaller screenshot.")
    try:
        probe = Image.open(io.BytesIO(data))
        fmt, size = probe.format, probe.size                      # read from the header; nothing is decoded yet
        probe.verify()
    except Exception as exc:  # noqa: BLE001 -- Pillow raises many types for a bad file
        raise OcrError("That file is not an image I can open. Please attach a PNG or JPG screenshot.") from exc
    if fmt not in ALLOWED_FORMATS:                                # judged by content, never by the file name
        raise OcrError("Please attach a PNG, JPG, BMP, TIFF or WebP screenshot.")
    if max(size) > MAX_SIDE:
        raise OcrError(f"The image is larger than {MAX_SIDE} pixels on a side. Please send a smaller screenshot.")
    return Image.open(io.BytesIO(data)), ALLOWED_FORMATS[fmt]


def redact(text: str) -> str:
    for pattern, repl in _SECRETS:
        text = pattern.sub(repl, text)
    return text


# ---------------------------------------------------------------- preparation

def _preprocess(img: Image.Image) -> Image.Image:
    """Grey, more contrast, sharpen, and enlarge small screenshots: Tesseract reads small text poorly."""
    img = img.convert("L")
    img = ImageEnhance.Contrast(img).enhance(2.0)
    img = img.filter(ImageFilter.SHARPEN)
    w, h = img.size
    if w < 1000 or h < 600:
        scale = max(1000 / w, 600 / h, 1.5)
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    return img


# ---------------------------------------------------------------- engines (each returns (text, confidence 0..1 or None))

def _find_tesseract() -> Optional[str]:
    explicit = os.environ.get("TESSERACT_CMD")
    if explicit and Path(explicit).exists():
        return explicit
    return shutil.which("tesseract") or next((p for p in _TESSERACT_PATHS if Path(p).exists()), None)


def _tesseract(img: Image.Image, lang: str) -> tuple[str, Optional[float]]:
    import pytesseract                                              # ImportError when not installed -> next engine
    cmd = _find_tesseract()
    if cmd is None:
        raise ImportError("the Tesseract program is not installed")
    pytesseract.pytesseract.tesseract_cmd = cmd
    data = pytesseract.image_to_data(img, lang=lang, output_type=pytesseract.Output.DICT)
    words = [(w, float(c)) for w, c in zip(data["text"], data["conf"]) if str(w).strip() and float(c) >= 0]
    lines: dict[tuple, list[str]] = {}
    for i, w in enumerate(data["text"]):
        if str(w).strip() and float(data["conf"][i]) >= 0:
            lines.setdefault((data["block_num"][i], data["par_num"][i], data["line_num"][i]), []).append(w)
    text = "\n".join(" ".join(ws) for ws in lines.values())
    return text, (round(sum(c for _, c in words) / len(words) / 100, 3) if words else None)


def _rapidocr(img: Image.Image, lang: str) -> tuple[str, Optional[float]]:
    from rapidocr_onnxruntime import RapidOCR                       # ImportError when not installed
    import numpy as np
    result, _ = RapidOCR()(np.array(img.convert("RGB")))
    if not result:
        return "", None
    return "\n".join(r[1] for r in result), round(sum(float(r[2]) for r in result) / len(result), 3)


ENGINES = {"tesseract": _tesseract, "rapidocr": _rapidocr}


def _run_engines(img: Image.Image, lang: str) -> tuple[str, Optional[float], Optional[str], Optional[str]]:
    """(text, confidence, engine name, failure reason). Tries each engine until one is available and runs."""
    wanted = os.environ.get("OCR_ENGINE", "").lower()
    names = [wanted] if wanted in ENGINES else list(ENGINES)
    reason = "no_engine"
    for name in names:
        try:
            text, conf = ENGINES[name](img, lang)
            return text, conf, name, None
        except ImportError as exc:
            log.info("OCR engine %s unavailable: %s", name, exc)
        except Exception as exc:  # noqa: BLE001 -- a broken engine must not take the upload down
            log.warning("OCR engine %s failed: %s", name, exc)
            reason = "engine_error"
    return "", None, None, reason


# ---------------------------------------------------------------- public API

def read_screenshot(data: bytes, lang: str = "eng") -> OcrResult:
    """Validate and read an uploaded image. Raises OcrError for a file we will not read; otherwise always returns a result,
    and `ok` says whether any text came out."""
    img, _ = validate_image(data)
    started = time.perf_counter()
    text, conf, engine, reason = _run_engines(_preprocess(img), lang)
    text = redact(text.strip())[:MAX_TEXT_CHARS]
    ctx = extract_error_context(text) if text else {"error_messages": [], "exit_codes": []}
    return OcrResult(ok=bool(text), text=text, confidence=conf, engine=engine, reason=None if text else (reason or "no_text"),
                     latency_ms=round((time.perf_counter() - started) * 1000, 1),
                     error_messages=ctx["error_messages"], exit_codes=ctx["exit_codes"])


def extract_text_from_image(source: Union[str, Path, bytes, io.BytesIO, Image.Image], lang: str = "eng", preprocess: bool = True) -> str:
    """The resolver track's original entry point: text only ('' when nothing could be read). Prefer read_screenshot."""
    if isinstance(source, Image.Image):
        img = source
    elif isinstance(source, (str, Path)):
        img = Image.open(source)
    elif isinstance(source, (bytes, io.BytesIO)):
        img = Image.open(io.BytesIO(source) if isinstance(source, bytes) else source)
    else:
        raise TypeError(f"Unsupported source type: {type(source)}")
    text, _, _, _ = _run_engines(_preprocess(img) if preprocess else img, lang)
    return redact(text.strip())


_ERROR_WORDS = ("error", "fatal", "failed", "denied", "refused", "cannot", "can't", "unable", "not found", "no such", "permission",
                "timeout", "timed out", "killed", "oom", "crash", "panic", "exceeded", "exit code")
_COMMAND_PREFIXES = ("$ ", "PS ", "docker ", "sudo docker ", "docker-compose ")
_EXIT_CODE = re.compile(r"exit(?:ed with)?(?:\s+status)?\s+(?:code\s+)?(\d+)", re.I)


def extract_error_context(text: str) -> dict[str, list[str]]:
    """The lines of OCR text that look like errors, any exit codes, and Docker-flavoured lines (for the preview and the message)."""
    errors: list[str] = []
    exit_codes: list[str] = []
    symptoms: list[str] = []
    for line in (ln.strip() for ln in text.splitlines()):
        if not line:
            continue
        low = line.lower()
        if any(kw in low for kw in _ERROR_WORDS):
            errors.append(line)
        exit_codes.extend(f"exit code {c}" for c in _EXIT_CODE.findall(line))
        if any(kw in low for kw in ("container", "image", "volume", "network", "port", "build", "compose", "daemon", "docker", "registry")):
            symptoms.append(line)
    return {"error_messages": errors[:10], "exit_codes": list(dict.fromkeys(exit_codes))[:5], "symptoms": symptoms[:10]}


def message_excerpt(text: str, max_chars: int = 500) -> str:
    """What goes into the customer's message: the error lines when there are any, with the command that produced them (a `$ docker pull
    nginx` line says what was being done), else the start of the text."""
    ctx = extract_error_context(text)
    if not ctx["error_messages"]:
        return " ".join(text.split())[:max_chars]
    commands = [ln.strip() for ln in text.splitlines() if ln.strip().startswith(_COMMAND_PREFIXES) and len(ln.strip()) <= 200][:2]
    return "\n".join([*commands, *ctx["error_messages"][:3]])[:max_chars]

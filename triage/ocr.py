"""OCR module — extract text from uploaded screenshots/images.

Uses pytesseract (Tesseract OCR) as primary engine.
Falls back to a simple PIL-based approach if tesseract is unavailable.

Usage:
    from triage.ocr import extract_text_from_image
    text = extract_text_from_image("screenshot.png")
"""
from __future__ import annotations

import io
import logging
import os
import shutil
import sys
from pathlib import Path
from typing import Optional, Union

from PIL import Image, ImageEnhance, ImageFilter

log = logging.getLogger(__name__)


def _configure_tesseract():
    if sys.platform == "win32":
        try:
            import pytesseract
            if shutil.which("tesseract"):
                return
            candidates = [
                r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
            ]
            for p in candidates:
                if Path(p).exists():
                    pytesseract.pytesseract.tesseract_cmd = p
                    return
        except ImportError:
            pass


_configure_tesseract()


def _preprocess(img: Image.Image) -> Image.Image:
    """Enhance image for better OCR accuracy."""
    # Convert to grayscale
    img = img.convert("L")
    # Increase contrast
    img = ImageEnhance.Contrast(img).enhance(2.0)
    # Sharpen
    img = img.filter(ImageFilter.SHARPEN)
    # Upscale small images (helps OCR accuracy)
    w, h = img.size
    if w < 1000 or h < 600:
        scale = max(1000 / w, 600 / h, 1.5)
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    return img


def extract_text_from_image(
    source: Union[str, Path, bytes, io.BytesIO, Image.Image],
    lang: str = "eng",
    preprocess: bool = True,
) -> str:
    """Extract text from an image file, bytes, or PIL Image.

    Args:
        source: file path, raw bytes, BytesIO, or PIL Image
        lang: Tesseract language code
        preprocess: whether to enhance the image before OCR

    Returns:
        Extracted text string (may be empty if nothing readable found)
    """
    # Load image
    if isinstance(source, Image.Image):
        img = source
    elif isinstance(source, (str, Path)):
        img = Image.open(source)
    elif isinstance(source, bytes):
        img = Image.open(io.BytesIO(source))
    elif isinstance(source, io.BytesIO):
        img = Image.open(source)
    else:
        raise TypeError(f"Unsupported source type: {type(source)}")

    if preprocess:
        img = _preprocess(img)

    # Try pytesseract first
    try:
        import pytesseract
        # Always set path explicitly
        import shutil as _sh
        _tess = _sh.which("tesseract")
        if not _tess:
            for _p in [
                r"C:\Users\kaavi\Downloads\Tesseract-OCR\Tesseract-OCR\tesseract.exe",
                r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
            ]:
                if Path(_p).exists():
                    _tess = _p
                    break
        if _tess:
            pytesseract.pytesseract.tesseract_cmd = _tess
        text = pytesseract.image_to_string(img, lang=lang)
        return text.strip()
    except ImportError:
        log.warning("pytesseract not installed, trying easyocr fallback")
    except Exception as e:
        log.warning(f"pytesseract failed: {e}, trying fallback")

    # Fallback: easyocr
    try:
        import easyocr
        reader = easyocr.Reader([lang[:2]])  # "eng" -> "en"
        # Convert PIL to bytes for easyocr
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        results = reader.readtext(buf.getvalue())
        return "\n".join(r[1] for r in results).strip()
    except ImportError:
        log.warning("easyocr not installed either")
    except Exception as e:
        log.warning(f"easyocr fallback failed: {e}")

    return ""


def extract_error_context(text: str) -> dict[str, list[str]]:
    """Parse OCR text to find error messages, exit codes, and key symptoms.

    Returns dict with keys: error_messages, exit_codes, symptoms
    """
    import re

    errors: list[str] = []
    exit_codes: list[str] = []
    symptoms: list[str] = []

    lines = text.splitlines()
    for line in lines:
        line = line.strip()
        if not line:
            continue
        # Error patterns common in Docker
        if any(kw in line.lower() for kw in [
            "error", "fatal", "failed", "denied", "refused",
            "cannot", "unable", "not found", "no such", "permission",
            "timeout", "killed", "oom", "crash", "panic",
        ]):
            errors.append(line)
        # Exit codes
        codes = re.findall(r"exit(?:ed with)?\s+(?:code\s+)?(\d+)", line, re.I)
        exit_codes.extend(f"exit code {c}" for c in codes)
        # Docker-specific symptoms
        if any(kw in line.lower() for kw in [
            "container", "image", "volume", "network", "port",
            "build", "compose", "daemon", "docker", "registry",
        ]):
            symptoms.append(line)

    return {
        "error_messages": errors[:10],    # cap at 10
        "exit_codes": exit_codes[:5],
        "symptoms": symptoms[:10],
    }

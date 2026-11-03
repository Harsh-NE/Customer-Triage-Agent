"""attachments.py -- screenshots a customer attaches: validated, read with OCR, kept on disk, served back only to people who may see the case.

Two steps, so the customer can check what was read before it is used:
  1. POST /api/attachments (the image)  ->  AttachmentStore.save(): the file is checked, OCR runs, the image and the OCR result are
     stored under uploads/<user id>/<sha256 prefix>.<ext> (+ .json), and the result is returned for the customer to correct.
  2. The message (new conversation or reply) carries `attachment_id` and the possibly corrected `screenshot_text`; the text that
     reaches the agents is the customer's own words plus the error lines of that text, as plain lines: the agents then treat a screenshot
     exactly like the same error typed in (a label in front of it measurably changed what the Clarifier asked).

The id is content-derived (hex + a fixed extension), never a client file name, so there is nothing to traverse. The screenshot's text is
masked for secrets (triage/ocr.py) and is untrusted input like everything else the customer sends.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Callable

from triage import ocr
from triage.api.service import ServiceError

ID_RE = re.compile(r"^[0-9a-f]{16}\.(png|jpg|bmp|tiff|webp)$")
MAX_SCREENSHOT_TEXT = 2000
MEDIA_TYPES = {"png": "image/png", "jpg": "image/jpeg", "bmp": "image/bmp", "tiff": "image/tiff", "webp": "image/webp"}


class AttachmentStore:
    def __init__(self, root: Path, reader: Callable[[bytes], ocr.OcrResult] = ocr.read_screenshot) -> None:
        self.root, self.reader = Path(root), reader

    def _dir(self, owner_id: int) -> Path:
        return self.root / str(int(owner_id))

    def path(self, owner_id: int, attachment_id: str) -> Path:
        if not ID_RE.match(attachment_id or ""):
            raise ServiceError(404, "attachment not found")
        p = self._dir(owner_id) / attachment_id
        if not p.is_file():
            raise ServiceError(404, "attachment not found")
        return p

    def save(self, owner_id: int, data: bytes) -> dict:
        try:
            _, ext = ocr.validate_image(data)
        except ocr.OcrError as exc:
            raise ServiceError(422, str(exc)) from exc
        att_id = f"{hashlib.sha256(data).hexdigest()[:16]}.{ext}"
        folder = self._dir(owner_id)
        folder.mkdir(parents=True, exist_ok=True)
        result = self.reader(data)
        (folder / att_id).write_bytes(data)
        meta = {"id": att_id, "ocr": result.to_dict()}
        (folder / f"{att_id}.json").write_text(json.dumps(meta), encoding="utf-8")
        return meta

    def meta(self, owner_id: int, attachment_id: str) -> dict:
        self.path(owner_id, attachment_id)                                    # existence + id check
        side = self._dir(owner_id) / f"{attachment_id}.json"
        return json.loads(side.read_text(encoding="utf-8")) if side.exists() else {"id": attachment_id, "ocr": {}}

    def prepare(self, owner_id: int, attachment_id: str, screenshot_text: str | None) -> dict:
        """What a message carries for its attachment: the id, the text the customer confirmed (their edit when they made one,
        else what OCR read), and the OCR facts for the engineer. Raises 404 for an id that is not this customer's."""
        meta = self.meta(owner_id, attachment_id)
        read = meta.get("ocr") or {}
        text = ocr.redact((screenshot_text if screenshot_text is not None else read.get("text", "")).strip())[:MAX_SCREENSHOT_TEXT]
        return {"id": attachment_id, "owner": int(owner_id), "text": text, "edited": screenshot_text is not None and text != read.get("text", ""),
                "ocr": {k: read.get(k) for k in ("ok", "confidence", "engine", "reason", "latency_ms", "low_confidence")}}

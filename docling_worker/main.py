"""Railway Docling conversion worker — PDF/PPTX/DOCX/… → HTML + markdown."""

from __future__ import annotations

import logging
import os
import secrets
import sys
import tempfile
from pathlib import Path

from typing import Optional

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("DOCLING_WORKER_MODE", "true")
# Never recurse to ourselves.
os.environ.pop("DOCLING_WORKER_URL", None)

from backend.documents.convert import _convert_local  # noqa: E402

logger = logging.getLogger(__name__)
app = FastAPI(title="NowIGetIt Docling Worker", version="0.1.0")


def _check_secret(authorization: Optional[str]) -> None:
    expected = (os.getenv("DOCLING_WORKER_SECRET") or "").strip()
    if not expected:
        return
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    if not secrets.compare_digest(token, expected):
        raise HTTPException(status_code=401, detail="Invalid token")


@app.get("/health")
def health() -> dict:
    docling_ok = False
    docling_version = None
    try:
        import docling

        docling_ok = True
        docling_version = getattr(docling, "__version__", "unknown")
    except ImportError:
        pass
    return {
        "ok": True,
        "service": "nowigetit-docling-worker",
        "docling_available": docling_ok,
        "docling_version": docling_version,
        "docling_worker_mode": os.getenv("DOCLING_WORKER_MODE", ""),
        "do_ocr": os.getenv("DOCLING_DO_OCR", "false"),
    }


@app.post("/convert")
async def convert(
    file: UploadFile = File(...),
    authorization: Optional[str] = Header(default=None),
    page_from: Optional[str] = Form(default=None),
    page_to: Optional[str] = Form(default=None),
) -> dict:
    _check_secret(authorization)
    filename = file.filename or "document.bin"
    suffix = Path(filename).suffix or ".bin"

    page_range = None
    if page_from and page_to:
        try:
            page_range = (int(page_from), int(page_to))
        except ValueError as exc:
            raise HTTPException(
                status_code=400, detail="page_from/page_to must be integers"
            ) from exc

    with tempfile.TemporaryDirectory(prefix="docling_in_") as tmp:
        path = Path(tmp) / f"upload{suffix}"
        path.write_bytes(await file.read())
        result = _convert_local(path, page_range=page_range)
        payload = result.model_dump()
        if payload.get("log"):
            payload["log"] = str(payload["log"])[-2500:]
        return payload

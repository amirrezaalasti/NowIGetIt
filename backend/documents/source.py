"""Turn uploaded files and library documents into source text for generation."""

from __future__ import annotations

import json
import re
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from backend import artifacts as base
from backend import supabase_db as db
from backend.documents.convert import convert_document
from backend.documents.schemas import SUPPORTED_EXTENSIONS
from backend.documents import store as doc_store

SOURCE_CAP = 80_000
MAX_SOURCES = 6
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
TEXT_EXTS = frozenset(
    {".txt", ".md", ".markdown", ".html", ".htm", ".adoc", ".asciidoc"}
)

_TAG_RE = re.compile(r"<[^>]+>")


def clean_source_ids(value: Optional[list[str]]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in value or []:
        item_id = str(raw or "").strip()
        if not item_id or item_id in seen:
            continue
        seen.add(item_id)
        cleaned.append(item_id)
        if len(cleaned) >= MAX_SOURCES:
            break
    return cleaned


def compose_learner_prompt(
    prompt: str,
    source_text: str,
    *,
    filenames: Optional[list[str]] = None,
) -> str:
    """Fold attached notes into the learner prompt the teaching pipeline reads."""
    prompt = (prompt or "").strip()
    source_text = (source_text or "").strip()
    if not source_text:
        return prompt
    names = ", ".join(n for n in (filenames or []) if n) or "attached notes"
    header = (
        f"The learner attached source material ({names}). Teach FROM this material: "
        "keep its facts, notation, examples, and claims. Do not invent a different "
        "topic. If the prompt is empty, explain the core idea of the source so a "
        "curious learner gets it.\n\n"
    )
    user_line = (
        f"Learner prompt:\n{prompt}\n\n"
        if prompt
        else "Learner prompt: (none — teach the attached material)\n\n"
    )
    return f"{header}{user_line}SOURCE MATERIAL:\n{source_text[:SOURCE_CAP]}"


def job_prompt_label(prompt: str, filenames: list[str]) -> str:
    text = (prompt or "").strip()
    if text:
        return text
    if filenames:
        return f"From {filenames[0]}"
    return "Attached source"


def _strip_html(html: str) -> str:
    text = _TAG_RE.sub(" ", html or "")
    return re.sub(r"\s+", " ", text).strip()


def _read_text_file(path: Path) -> str:
    raw = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix.lower() in {".html", ".htm"}:
        return _strip_html(raw)
    return raw.strip()


def extract_path(path: Path, *, filename: str = "") -> str:
    """Plain text from a local file. Uses Docling for decks/PDFs/images."""
    ext = path.suffix.lower()
    if ext in TEXT_EXTS:
        return _read_text_file(path)[:SOURCE_CAP]
    if ext not in SUPPORTED_EXTENSIONS and ext not in TEXT_EXTS:
        raise ValueError(f"Unsupported file type: {filename or path.name}")
    converted = convert_document(path)
    if not converted.ok:
        raise ValueError(converted.error or f"Could not read {filename or path.name}")
    text = (converted.markdown or "").strip() or _strip_html(converted.html or "")
    if not text:
        raise ValueError(f"No readable text in {filename or path.name}")
    return text[:SOURCE_CAP]


def load_source_text(item_id: str, *, user_id: Optional[str] = None) -> dict[str, Any]:
    """Load markdown/plain text from a document or extracted source artifact."""
    if user_id:
        try:
            base.assert_job_owner(item_id, user_id)
        except PermissionError as exc:
            raise ValueError("One of the attached files is not available") from exc
    root = base.artifacts_root() / item_id
    if not root.exists():
        raise FileNotFoundError(item_id)
    meta: dict[str, Any] = {}
    meta_path = root / "meta.json"
    if meta_path.exists():
        try:
            loaded = json.loads(meta_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                meta = loaded
        except json.JSONDecodeError:
            meta = {}
    title = str(meta.get("title") or meta.get("source_filename") or item_id)
    filename = str(meta.get("source_filename") or title)
    embedded = str(meta.get("source_text") or "").strip()
    if embedded:
        md_path = root / "source.md"
        if not md_path.exists():
            md_path.write_text(embedded[:SOURCE_CAP], encoding="utf-8")
        return {
            "id": item_id,
            "title": title,
            "filename": filename,
            "text": embedded[:SOURCE_CAP],
            "char_count": min(len(embedded), SOURCE_CAP),
        }
    for name in ("source.md", "document.md"):
        path = root / name
        if path.exists():
            text = path.read_text(encoding="utf-8", errors="replace").strip()
            if text:
                return {
                    "id": item_id,
                    "title": title,
                    "filename": filename,
                    "text": text[:SOURCE_CAP],
                    "char_count": min(len(text), SOURCE_CAP),
                }
    try:
        manifest = doc_store.load_manifest(item_id)
    except FileNotFoundError:
        manifest = None
    if manifest:
        parts: list[str] = []
        for slide in manifest.slides:
            heading = slide.title or f"Slide {slide.index + 1}"
            body = (slide.plain_text or "").strip()
            if body:
                parts.append(f"## {heading}\n{body}")
        text = "\n\n".join(parts).strip()
        if text:
            return {
                "id": item_id,
                "title": manifest.title or title,
                "filename": manifest.source_filename or filename,
                "text": text[:SOURCE_CAP],
                "char_count": min(len(text), SOURCE_CAP),
            }
    raise ValueError(f"No readable text in {item_id}")


def resolve_sources(
    source_ids: list[str],
    *,
    user_id: Optional[str] = None,
) -> tuple[str, list[str]]:
    """Join multiple sources. Returns (combined_text, filenames)."""
    chunks: list[str] = []
    names: list[str] = []
    seen: set[str] = set()
    for raw_id in source_ids[:MAX_SOURCES]:
        item_id = str(raw_id or "").strip()
        if not item_id or item_id in seen:
            continue
        seen.add(item_id)
        item = load_source_text(item_id, user_id=user_id)
        names.append(str(item.get("filename") or item.get("title") or item_id))
        chunks.append(
            f"--- {item.get('filename') or item.get('title')} ---\n{item['text']}"
        )
    combined = "\n\n".join(chunks).strip()[:SOURCE_CAP]
    return combined, names


def prepare_generation_prompt(
    prompt: str,
    source_ids: Optional[list[str]] = None,
    *,
    user_id: Optional[str] = None,
) -> tuple[str, str, list[str]]:
    """Return (teaching_prompt, display_prompt, filenames)."""
    ids = clean_source_ids(source_ids)
    prompt = (prompt or "").strip()
    if not ids:
        if not prompt:
            raise ValueError("Provide a prompt or attach a file")
        return prompt, prompt, []
    try:
        text, names = resolve_sources(ids, user_id=user_id)
    except FileNotFoundError as exc:
        raise ValueError("One of the attached files could not be found") from exc
    if not text.strip():
        raise ValueError("Could not read text from the attached files")
    return (
        compose_learner_prompt(prompt, text, filenames=names),
        job_prompt_label(prompt, names),
        names,
    )


def save_extracted_source(
    *,
    filename: str,
    text: str,
    user_id: Optional[str] = None,
    user_email: Optional[str] = None,
    user_name: Optional[str] = None,
    original_path: Optional[Path] = None,
) -> dict[str, Any]:
    item_id = f"src_{uuid.uuid4().hex[:16]}"
    root = base.artifacts_root() / item_id
    root.mkdir(parents=True, exist_ok=True)
    (root / "source").mkdir(exist_ok=True)
    title = Path(filename).stem or filename
    created = datetime.now(timezone.utc).isoformat()
    (root / "source.md").write_text(text[:SOURCE_CAP], encoding="utf-8")
    if original_path and original_path.exists():
        dest = root / "source" / Path(filename).name
        dest.write_bytes(original_path.read_bytes())
    base.write_json(
        root / "meta.json",
        {
            "job_id": item_id,
            "kind": "source",
            "prompt": f"source:{filename}",
            "source_filename": filename,
            "title": title,
            "created_at": created,
            "user_id": user_id,
            "user_email": user_email,
            "user_name": user_name,
            "status": "ready",
            "char_count": min(len(text), SOURCE_CAP),
            "source_text": text[:SOURCE_CAP],
        },
    )
    if user_id:
        db.upsert_job(
            job_id=item_id,
            user_id=user_id,
            prompt=f"source:{filename}",
            title=title,
            status="complete",
        )
        base.sync_job_state(item_id, status="complete")
    return {
        "id": item_id,
        "title": title,
        "filename": filename,
        "char_count": min(len(text), SOURCE_CAP),
        "preview": text[:400],
        "kind": "source",
    }


def extract_upload(
    data: bytes,
    *,
    filename: str,
    user_id: Optional[str] = None,
    user_email: Optional[str] = None,
    user_name: Optional[str] = None,
) -> dict[str, Any]:
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError("File is larger than 25 MB")
    name = Path(filename or "upload").name
    ext = Path(name).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS and ext not in TEXT_EXTS:
        raise ValueError(f"Unsupported file type: {name}")
    suffix = ext or ".bin"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(data)
        tmp_path = Path(tmp.name)
    try:
        text = extract_path(tmp_path, filename=name)
        if not text.strip():
            raise ValueError(f"No readable text in {name}")
        return save_extracted_source(
            filename=name,
            text=text,
            user_id=user_id,
            user_email=user_email,
            user_name=user_name,
            original_path=tmp_path,
        )
    finally:
        tmp_path.unlink(missing_ok=True)


def list_library_sources(*, user_id: str, limit: int = 30) -> list[dict[str, Any]]:
    jobs = base.list_jobs(
        limit=max(limit * 3, 40), user_id=user_id, include_sources=True
    )
    items: list[dict[str, Any]] = []
    for job in jobs:
        job_id = str(job.get("job_id") or "")
        kind = str(job.get("kind") or "")
        if kind not in {"document", "source"} and not job_id.startswith(
            ("doc_", "src_")
        ):
            continue
        items.append(
            {
                "id": job_id,
                "title": job.get("title") or job_id,
                "filename": job.get("prompt") or "",
                "kind": kind or ("document" if job_id.startswith("doc_") else "source"),
                "created_at": job.get("created_at"),
                "status": job.get("status"),
            }
        )
        if len(items) >= limit:
            break
    return items

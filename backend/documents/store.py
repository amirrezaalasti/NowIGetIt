"""Filesystem helpers for document artifacts."""

from __future__ import annotations

import json
import logging
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from backend import artifacts as base
from backend import supabase_db as db
from backend.documents.schemas import DocumentAnnotation, DocumentManifest

logger = logging.getLogger(__name__)


def new_doc_id() -> str:
    return f"doc_{uuid.uuid4().hex[:16]}"


def doc_dir(doc_id: str) -> Path:
    path = base.artifacts_root() / doc_id
    path.mkdir(parents=True, exist_ok=True)
    (path / "slides").mkdir(exist_ok=True)
    (path / "assets").mkdir(exist_ok=True)
    (path / "source").mkdir(exist_ok=True)
    return path


def init_document(
    doc_id: str,
    *,
    source_filename: str,
    user_id: Optional[str] = None,
    user_email: Optional[str] = None,
    user_name: Optional[str] = None,
) -> Path:
    root = doc_dir(doc_id)
    base.write_json(
        root / "meta.json",
        {
            "job_id": doc_id,
            "doc_id": doc_id,
            "kind": "document",
            "prompt": f"document:{source_filename}",
            "source_filename": source_filename,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "user_id": user_id,
            "user_email": user_email,
            "user_name": user_name,
            "status": "converting",
        },
    )
    if user_id:
        db.upsert_job(
            job_id=doc_id,
            user_id=user_id,
            prompt=f"document:{source_filename}",
            title=source_filename,
            status="running",
        )
        base.sync_job_state(doc_id, status="running")
    return root


def save_manifest(doc_id: str, manifest: DocumentManifest | dict[str, Any]) -> str:
    data = (
        manifest.model_dump()
        if isinstance(manifest, DocumentManifest)
        else manifest
    )
    path = base.write_json(doc_dir(doc_id) / "document.json", data)
    meta_path = doc_dir(doc_id) / "meta.json"
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            meta = {}
        meta["status"] = data.get("status", "ready")
        meta["title"] = data.get("title")
        meta["slide_count"] = data.get("slide_count", 0)
        base.write_json(meta_path, meta)
    if data.get("status") == "ready":
        user_id = None
        if meta_path.exists():
            try:
                user_id = json.loads(meta_path.read_text(encoding="utf-8")).get(
                    "user_id"
                )
            except json.JSONDecodeError:
                pass
        if isinstance(user_id, str) and user_id:
            db.upsert_job(
                job_id=doc_id,
                user_id=user_id,
                prompt=f"document:{data.get('source_filename') or doc_id}",
                title=data.get("title") or data.get("source_filename"),
                status="complete",
            )
            base.sync_job_state(doc_id, status="complete")
    return path


def load_manifest(doc_id: str) -> DocumentManifest:
    path = doc_dir(doc_id) / "document.json"
    if not path.exists():
        raise FileNotFoundError(doc_id)
    data = json.loads(path.read_text(encoding="utf-8"))
    return DocumentManifest.model_validate(data)


def annotations_path(doc_id: str) -> Path:
    return doc_dir(doc_id) / "annotations.json"


def list_annotations(doc_id: str) -> list[dict[str, Any]]:
    path = annotations_path(doc_id)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def add_annotation(
    doc_id: str,
    *,
    slide_id: str,
    block_id: Optional[str],
    action: str,
    message: str,
    reply: str,
    author: str = "user",
    pinned: bool = True,
) -> DocumentAnnotation:
    items = list_annotations(doc_id)
    entry = DocumentAnnotation(
        id=f"ann_{uuid.uuid4().hex[:12]}",
        doc_id=doc_id,
        slide_id=slide_id,
        block_id=block_id,
        action=action,
        message=message,
        reply=reply,
        author=author,
        created_at=datetime.now(timezone.utc).isoformat(),
        pinned=pinned,
    )
    items.append(entry.model_dump())
    base.write_json(annotations_path(doc_id), items)
    return entry


def delete_annotation(doc_id: str, comment_id: str) -> bool:
    items = list_annotations(doc_id)
    next_items = [i for i in items if i.get("id") != comment_id]
    if len(next_items) == len(items):
        return False
    base.write_json(annotations_path(doc_id), next_items)
    return True


def list_slide_comments(doc_id: str, slide_id: str) -> list[dict[str, Any]]:
    return [
        item
        for item in list_annotations(doc_id)
        if item.get("slide_id") == slide_id
    ]


def list_documents(*, user_id: Optional[str] = None, limit: int = 50) -> list[dict[str, Any]]:
    jobs = base.list_jobs(limit=max(limit * 3, 50), user_id=user_id)
    docs: list[dict[str, Any]] = []
    for job in jobs:
        job_id = str(job.get("job_id") or "")
        root = base.artifacts_root() / job_id
        # Skip remote-only ghosts (deleted locally but row still present).
        if not root.exists():
            continue
        if not job_id.startswith("doc_"):
            # Also accept kind=document from meta
            meta_path = root / "meta.json"
            kind = None
            if meta_path.exists():
                try:
                    kind = json.loads(meta_path.read_text(encoding="utf-8")).get("kind")
                except json.JSONDecodeError:
                    kind = None
            if kind != "document":
                continue
        title = job.get("title")
        source_filename = None
        slide_count = 0
        status = job.get("status") or ("complete" if job.get("has_result") else "unknown")
        manifest_path = root / "document.json"
        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                title = manifest.get("title") or title
                source_filename = manifest.get("source_filename")
                slide_count = int(manifest.get("slide_count") or 0)
                status = manifest.get("status") or status
            except (json.JSONDecodeError, TypeError, ValueError):
                pass
        else:
            meta_path = root / "meta.json"
            if meta_path.exists():
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                    source_filename = meta.get("source_filename")
                    title = meta.get("title") or title or source_filename
                    slide_count = int(meta.get("slide_count") or 0)
                    status = meta.get("status") or status
                except (json.JSONDecodeError, TypeError, ValueError):
                    pass
            else:
                continue
        docs.append(
            {
                "doc_id": job_id,
                "title": title,
                "source_filename": source_filename,
                "created_at": job.get("created_at"),
                "status": status,
                "slide_count": slide_count,
                "kind": "document",
            }
        )
        if len(docs) >= limit:
            break
    return docs


def safe_filename(name: str) -> str:
    cleaned = re.sub(r"[^\w.\- ()\[\]]+", "_", name).strip("._ ")
    return (cleaned or "document")[:180]


def delete_document(doc_id: str, *, user_id: str) -> None:
    """Delete document artifacts from disk and the Supabase job row."""
    root = base.artifacts_root() / doc_id
    if root.exists():
        base.assert_job_owner(doc_id, user_id)
        try:
            shutil.rmtree(root)
        except OSError as exc:
            logger.exception("Failed to remove document dir %s", doc_id)
            raise RuntimeError(f"Failed to delete document files: {exc}") from exc
    else:
        # Local already gone — still clear the remote row (idempotent).
        logger.info("Document dir missing for %s; clearing remote job row", doc_id)

    try:
        db.delete_job(job_id=doc_id, user_id=user_id)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Failed to remove job row: {exc}") from exc

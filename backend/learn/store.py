"""Filesystem helpers for learn artifacts (podcast / quiz / interactive)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from backend import artifacts as base
from backend import supabase_db as db

KINDS = frozenset({"podcast", "quiz", "interactive"})

_PREFIX = {
    "podcast": "pod",
    "quiz": "quiz",
    "interactive": "lab",
}


def new_id(kind: str) -> str:
    prefix = _PREFIX.get(kind, "learn")
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def infer_kind(job_id: str, meta: Optional[dict[str, Any]] = None) -> str:
    if isinstance(meta, dict):
        kind = str(meta.get("kind") or "").strip()
        if kind in KINDS or kind in {"video", "document"}:
            return kind
    if job_id.startswith("doc_"):
        return "document"
    if job_id.startswith("pod_"):
        return "podcast"
    if job_id.startswith("quiz_"):
        return "quiz"
    if job_id.startswith("lab_"):
        return "interactive"
    return "video"


def item_dir(item_id: str) -> Path:
    path = base.artifacts_root() / item_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def init_item(
    item_id: str,
    *,
    kind: str,
    prompt: str,
    settings: dict[str, Any],
    user_id: Optional[str] = None,
    user_email: Optional[str] = None,
    user_name: Optional[str] = None,
) -> Path:
    root = item_dir(item_id)
    created = datetime.now(timezone.utc).isoformat()
    base.write_json(
        root / "meta.json",
        {
            "job_id": item_id,
            "kind": kind,
            "prompt": prompt,
            "created_at": created,
            "settings": settings,
            "user_id": user_id,
            "user_email": user_email,
            "user_name": user_name,
            "status": "running",
            "title": prompt[:80],
        },
    )
    if user_id:
        db.upsert_job(
            job_id=item_id,
            user_id=user_id,
            prompt=prompt,
            title=prompt[:80],
            status="running",
        )
        base.sync_job_state(item_id, status="running")
    return root


def patch_meta(item_id: str, **fields: Any) -> dict[str, Any]:
    path = item_dir(item_id) / "meta.json"
    meta: dict[str, Any] = {}
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                meta = loaded
        except json.JSONDecodeError:
            meta = {}
    meta.update({k: v for k, v in fields.items() if v is not None})
    base.write_json(path, meta)
    return meta


def save_payload(item_id: str, payload: dict[str, Any]) -> str:
    kind = str(payload.get("kind") or "learn")
    name = {
        "podcast": "podcast.json",
        "quiz": "quiz.json",
        "interactive": "interactive.json",
    }.get(kind, "result.json")
    path = base.write_json(item_dir(item_id) / name, payload)
    base.write_json(item_dir(item_id) / "result.json", payload)
    title = payload.get("title")
    status = payload.get("status") or "ready"
    patch_meta(item_id, title=title, status=status)
    user_id = None
    meta_path = item_dir(item_id) / "meta.json"
    if meta_path.exists():
        try:
            user_id = json.loads(meta_path.read_text(encoding="utf-8")).get("user_id")
        except json.JSONDecodeError:
            user_id = None
    if isinstance(user_id, str) and user_id:
        db.upsert_job(
            job_id=item_id,
            user_id=user_id,
            prompt=payload.get("prompt"),
            title=title,
            status="complete" if status in {"ready", "complete"} else status,
        )
        base.sync_job_state(
            item_id,
            status="complete" if status in {"ready", "complete"} else str(status),
        )
    return path


def load_payload(item_id: str) -> dict[str, Any]:
    root = item_dir(item_id)
    for name in ("podcast.json", "quiz.json", "interactive.json", "result.json"):
        path = root / name
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    raise FileNotFoundError(item_id)


def save_progress(item_id: str, progress: dict[str, Any]) -> str:
    return base.write_json(item_dir(item_id) / "progress.json", progress)


def load_progress(item_id: str) -> dict[str, Any]:
    path = item_dir(item_id) / "progress.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def save_attempts(item_id: str, attempts: list[dict[str, Any]]) -> str:
    return base.write_json(item_dir(item_id) / "attempts.json", attempts)


def load_attempts(item_id: str) -> list[dict[str, Any]]:
    path = item_dir(item_id) / "attempts.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def urls_for(item_id: str, payload: dict[str, Any]) -> dict[str, str]:
    kind = str(payload.get("kind") or "")
    urls: dict[str, str] = {
        "result": f"/api/jobs/{item_id}/file/result.json",
        "meta": f"/api/jobs/{item_id}/file/meta.json",
    }
    root = item_dir(item_id)
    if kind == "podcast":
        urls["podcast"] = f"/api/jobs/{item_id}/file/podcast.json"
        if (root / "podcast.wav").exists():
            urls["audio"] = f"/api/jobs/{item_id}/file/podcast.wav"
        elif (root / "podcast.mp3").exists():
            urls["audio"] = f"/api/jobs/{item_id}/file/podcast.mp3"
    elif kind == "quiz":
        urls["quiz"] = f"/api/jobs/{item_id}/file/quiz.json"
    elif kind == "interactive":
        urls["interactive"] = f"/api/jobs/{item_id}/file/interactive.json"
    return urls

"""MongoDB Atlas persistence for users, job index, and usage.

Videos stay on disk (ARTIFACTS_ROOT). Atlas M0 is too small for mp4 files.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

_LOCK = threading.Lock()
_state: dict[str, Any] = {"uri": None, "client": None}


def configured() -> bool:
    return bool(_uri())


def _uri() -> str:
    return (os.getenv("MONGODB_URI") or os.getenv("MONGO_URI") or "").strip()


def _db_name() -> str:
    return (os.getenv("MONGODB_DB") or "nowigetit").strip() or "nowigetit"


def close() -> None:
    with _LOCK:
        client = _state.get("client")
        if client is not None:
            client.close()
        _state["client"] = None
        _state["uri"] = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _period_start() -> str:
    return datetime.now(timezone.utc).replace(day=1).date().isoformat()


def _client():
    from pymongo import MongoClient
    from pymongo.server_api import ServerApi

    uri = _uri()
    if not uri:
        raise RuntimeError("MONGODB_URI is not set")
    current = _state.get("client")
    if current is not None and _state.get("uri") == uri:
        return current
    if current is not None:
        current.close()
    client = MongoClient(
        uri,
        server_api=ServerApi("1"),
        serverSelectionTimeoutMS=8000,
        connectTimeoutMS=8000,
    )
    _state["client"] = client
    _state["uri"] = uri
    db = client[_db_name()]
    db.jobs.create_index([("user_id", 1), ("created_at", -1)])
    db.monthly_usage.create_index([("user_id", 1), ("period_start", 1)], unique=True)
    db.llm_usage.create_index([("user_id", 1), ("created_at", -1)])
    return client


def _db():
    return _client()[_db_name()]


def ping() -> bool:
    if not configured():
        return False
    try:
        with _LOCK:
            _client().admin.command("ping")
        return True
    except Exception:  # noqa: BLE001
        return False


def ensure_user(
    *,
    user_id: str,
    email: Optional[str] = None,
    name: Optional[str] = None,
    image_url: Optional[str] = None,
) -> dict[str, Any]:
    now = _now()
    updates: dict[str, Any] = {"updated_at": now}
    if email is not None:
        updates["email"] = email
    if name is not None:
        updates["name"] = name
    if image_url is not None:
        updates["image_url"] = image_url
    with _LOCK:
        _db().users.update_one(
            {"_id": user_id},
            {"$set": updates, "$setOnInsert": {"created_at": now}},
            upsert=True,
        )
        row = _db().users.find_one({"_id": user_id})
    if not row:
        return {"id": user_id, "email": email, "name": name}
    return {
        "id": row["_id"],
        "email": row.get("email"),
        "name": row.get("name"),
        "image_url": row.get("image_url"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def get_user_openrouter_key(user_id: str) -> Optional[str]:
    from backend.user_secrets import decrypt_secret

    with _LOCK:
        row = _db().users.find_one({"_id": user_id}, {"openrouter_api_key_enc": 1})
    if not row:
        return None
    return decrypt_secret(row.get("openrouter_api_key_enc"))


def user_has_openrouter_key(user_id: str) -> bool:
    with _LOCK:
        row = _db().users.find_one({"_id": user_id}, {"openrouter_api_key_enc": 1})
    if not row:
        return False
    enc = row.get("openrouter_api_key_enc")
    return bool(enc and str(enc).strip())


def set_user_openrouter_key(user_id: str, api_key: str) -> dict[str, Any]:
    from backend.user_secrets import encrypt_secret, key_fingerprint, mask_api_key

    plain = (api_key or "").strip()
    if not plain:
        raise ValueError("API key is empty")
    enc = encrypt_secret(plain)
    now = _now()
    with _LOCK:
        _db().users.update_one(
            {"_id": user_id},
            {
                "$set": {
                    "openrouter_api_key_enc": enc,
                    "updated_at": now,
                },
                "$setOnInsert": {"created_at": now},
            },
            upsert=True,
        )
    return {
        "configured": True,
        "masked_key": mask_api_key(plain),
        "fingerprint": key_fingerprint(plain),
    }


def clear_user_openrouter_key(user_id: str) -> dict[str, Any]:
    now = _now()
    with _LOCK:
        _db().users.update_one(
            {"_id": user_id},
            {"$set": {"openrouter_api_key_enc": None, "updated_at": now}},
        )
    return {"configured": False, "masked_key": None, "fingerprint": None}


def _empty_usage(user_id: str) -> dict[str, Any]:
    return {
        "user_id": user_id,
        "period_start": _period_start(),
        "llm": {
            "tokens_used": 0,
            "tokens_limit": 0,
            "requests_used": 0,
            "requests_limit": 0,
        },
        "storage": {"bytes_used": 0, "bytes_limit": 0},
        "unlimited": True,
    }


def _storage_bytes(user_id: str) -> int:
    pipeline = [
        {"$match": {"user_id": user_id}},
        {"$group": {"_id": None, "total": {"$sum": "$storage_bytes"}}},
    ]
    with _LOCK:
        rows = list(_db().jobs.aggregate(pipeline))
    stored = int((rows[0]["total"] if rows else 0) or 0)
    if stored > 0:
        return stored
    from backend.artifacts import artifacts_root

    root = artifacts_root()
    if not root.exists():
        return 0
    total = 0
    for path in root.iterdir():
        if not path.is_dir() or path.name.startswith(("_", ".")):
            continue
        meta_path = path / "meta.json"
        if not meta_path.exists():
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if meta.get("user_id") != user_id:
            continue
        for item in path.rglob("*"):
            if item.is_file():
                try:
                    total += item.stat().st_size
                except OSError:
                    continue
    return total


def get_user_usage(user_id: str) -> dict[str, Any]:
    period = _period_start()
    with _LOCK:
        row = _db().monthly_usage.find_one({"user_id": user_id, "period_start": period})
    usage = _empty_usage(user_id)
    if row:
        usage["llm"]["requests_used"] = int(row.get("requests_used") or 0)
        usage["llm"]["tokens_used"] = int(row.get("tokens_used") or 0)
    usage["storage"]["bytes_used"] = _storage_bytes(user_id)
    return usage


def reserve_generation(user_id: str, *, estimated_tokens: int = 25_000) -> dict[str, Any]:
    del estimated_tokens
    period = _period_start()
    with _LOCK:
        _db().monthly_usage.update_one(
            {"user_id": user_id, "period_start": period},
            {"$inc": {"requests_used": 1}, "$setOnInsert": {"tokens_used": 0}},
            upsert=True,
        )
    return get_user_usage(user_id)


def record_llm_usage(
    *,
    user_id: str,
    tokens_in: int = 0,
    tokens_out: int = 0,
    job_id: Optional[str] = None,
    kind: str = "llm",
    model: Optional[str] = None,
) -> None:
    added = max(int(tokens_in or 0), 0) + max(int(tokens_out or 0), 0)
    if added <= 0:
        return
    period = _period_start()
    with _LOCK:
        _db().llm_usage.insert_one(
            {
                "user_id": user_id,
                "job_id": job_id,
                "kind": kind,
                "model": model,
                "tokens_in": int(tokens_in or 0),
                "tokens_out": int(tokens_out or 0),
                "created_at": _now(),
            }
        )
        _db().monthly_usage.update_one(
            {"user_id": user_id, "period_start": period},
            {"$inc": {"tokens_used": added}, "$setOnInsert": {"requests_used": 0}},
            upsert=True,
        )


def upsert_job(
    *,
    job_id: str,
    user_id: str,
    prompt: Optional[str] = None,
    title: Optional[str] = None,
    status: str = "running",
) -> None:
    now = _now()
    sets: dict[str, Any] = {"user_id": user_id, "status": status, "updated_at": now}
    if prompt is not None:
        sets["prompt"] = prompt
    if title is not None:
        sets["title"] = title
    with _LOCK:
        _db().jobs.update_one(
            {"_id": job_id},
            {"$set": sets, "$setOnInsert": {"created_at": now, "storage_bytes": 0}},
            upsert=True,
        )


def save_job_state(
    *,
    job_id: str,
    user_id: str,
    prompt: Optional[str] = None,
    title: Optional[str] = None,
    status: Optional[str] = None,
    meta: Optional[dict[str, Any]] = None,
    plan: Optional[dict[str, Any]] = None,
    events: Optional[list[dict[str, Any]]] = None,
) -> None:
    now = _now()
    created = None
    if isinstance(meta, dict) and isinstance(meta.get("created_at"), str):
        created = meta["created_at"]
    sets: dict[str, Any] = {"user_id": user_id, "updated_at": now}
    if prompt is not None:
        sets["prompt"] = prompt
    if title is not None:
        sets["title"] = title
    if status is not None:
        sets["status"] = status
    if meta is not None:
        sets["meta"] = meta
    if plan is not None:
        sets["plan"] = plan
    if events is not None:
        sets["events"] = events
    insert: dict[str, Any] = {"created_at": created or now, "storage_bytes": 0}
    if status is None:
        insert["status"] = "running"
    with _LOCK:
        _db().jobs.update_one(
            {"_id": job_id},
            {"$set": sets, "$setOnInsert": insert},
            upsert=True,
        )


def _job_payload(row: dict[str, Any]) -> dict[str, Any]:
    from backend.artifacts import artifacts_root

    job_id = str(row.get("_id") or row.get("job_id") or "")
    root = artifacts_root() / job_id
    return {
        "id": job_id,
        "job_id": job_id,
        "user_id": row.get("user_id"),
        "prompt": row.get("prompt"),
        "title": row.get("title"),
        "status": row.get("status"),
        "meta": row.get("meta"),
        "plan": row.get("plan"),
        "events": row.get("events") or [],
        "created_at": row.get("created_at"),
        "has_result": (root / "result.json").exists(),
        "has_final_video": (root / "final.mp4").exists()
        or (root / "document.json").exists(),
        "storage_bytes": int(row.get("storage_bytes") or 0),
    }


def get_job_state(job_id: str, user_id: str) -> Optional[dict[str, Any]]:
    with _LOCK:
        row = _db().jobs.find_one({"_id": job_id, "user_id": user_id})
    if not row:
        return None
    return _job_payload(row)


def _index_disk_jobs(user_id: str) -> None:
    from backend.artifacts import artifacts_root

    root = artifacts_root()
    if not root.exists():
        return
    now = _now()
    ops = []
    from pymongo import UpdateOne

    for path in root.iterdir():
        if not path.is_dir() or path.name.startswith(("_", ".")):
            continue
        meta_path = path / "meta.json"
        if not meta_path.exists():
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if meta.get("user_id") != user_id:
            continue
        title = meta.get("title")
        plan = None
        plan_path = path / "scene_plan.json"
        if plan_path.exists():
            try:
                plan = json.loads(plan_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                plan = None
            if isinstance(plan, dict) and not title:
                title = plan.get("title")
        status = str(meta.get("status") or "")
        if (path / "result.json").exists() or (path / "final.mp4").exists():
            status = status or "complete"
        sets: dict[str, Any] = {
            "user_id": user_id,
            "updated_at": now,
            "meta": meta,
        }
        if isinstance(meta.get("prompt"), str):
            sets["prompt"] = meta["prompt"]
        if isinstance(title, str):
            sets["title"] = title
        if status:
            sets["status"] = status
        if isinstance(plan, dict):
            sets["plan"] = plan
        ops.append(
            UpdateOne(
                {"_id": path.name},
                {
                    "$set": sets,
                    "$setOnInsert": {
                        "created_at": str(meta.get("created_at") or now),
                        "storage_bytes": 0,
                    },
                },
                upsert=True,
            )
        )
    if ops:
        with _LOCK:
            _db().jobs.bulk_write(ops, ordered=False)


def list_user_jobs(user_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
    _index_disk_jobs(user_id)
    with _LOCK:
        rows = list(
            _db()
            .jobs.find({"user_id": user_id})
            .sort("created_at", -1)
            .limit(max(int(limit), 1))
        )
    return [_job_payload(row) for row in rows]


def sync_job_storage(*, user_id: str, job_id: str, job_path: Path) -> None:
    size = 0
    if job_path.exists():
        for item in job_path.rglob("*"):
            if item.is_file():
                try:
                    size += item.stat().st_size
                except OSError:
                    continue
    with _LOCK:
        _db().jobs.update_one(
            {"_id": job_id, "user_id": user_id},
            {"$set": {"storage_bytes": size, "updated_at": _now()}},
        )


def delete_job(*, job_id: str, user_id: str) -> None:
    with _LOCK:
        _db().jobs.delete_one({"_id": job_id, "user_id": user_id})

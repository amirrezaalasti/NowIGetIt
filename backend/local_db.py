"""Storage mode + MongoDB or SQLite persistence when Supabase is off."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Literal, Optional

_LOCK = threading.Lock()
StorageMode = Literal["local", "mongo", "supabase"]


def _env_use_supabase() -> Optional[bool]:
    raw = (os.getenv("USE_SUPABASE") or "").strip().lower()
    if raw in {"0", "false", "no", "off"}:
        return False
    if raw in {"1", "true", "yes", "on"}:
        return True
    return None


def credentials_configured() -> bool:
    url = (
        os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL") or ""
    ).strip()
    key = (os.getenv("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
    return bool(url and key)


def supabase_available() -> bool:
    if _env_use_supabase() is False:
        return False
    return credentials_configured()


def mongo_configured() -> bool:
    return bool((os.getenv("MONGODB_URI") or os.getenv("MONGO_URI") or "").strip())


def _local_root() -> Path:
    from backend.artifacts import artifacts_root

    path = artifacts_root() / "_local"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _disk_pref() -> Optional[StorageMode]:
    mode = _read_json(_local_root() / "config.json").get("mode")
    if mode in {"local", "mongo", "supabase"}:
        return mode
    return None


def storage_mode() -> StorageMode:
    if supabase_available() and _disk_pref() != "local" and _disk_pref() != "mongo":
        return "supabase"
    if mongo_configured() and _disk_pref() != "local":
        return "mongo"
    return "local"


def set_storage_mode(mode: StorageMode) -> StorageMode:
    if mode not in {"local", "mongo", "supabase"}:
        raise ValueError("mode must be 'local', 'mongo', or 'supabase'")
    if mode == "supabase" and not supabase_available():
        raise ValueError("Supabase is not available.")
    if mode == "mongo" and not mongo_configured():
        raise ValueError("MongoDB is not configured (set MONGODB_URI).")
    with _LOCK:
        _write_json(_local_root() / "config.json", {"mode": mode})
    return storage_mode()


def _impl():
    if storage_mode() == "mongo":
        try:
            import pymongo  # noqa: F401
            from backend import mongo_db

            return mongo_db
        except Exception:  # noqa: BLE001
            # Prefer SQLite over a broken Mongo path so BYOK / usage keep working.
            pass
    from backend import sqlite_db

    return sqlite_db


def ensure_user(**kwargs):
    return _impl().ensure_user(**kwargs)


def get_user_usage(user_id: str):
    return _impl().get_user_usage(user_id)


def get_user_openrouter_key(user_id: str):
    return _impl().get_user_openrouter_key(user_id)


def user_has_openrouter_key(user_id: str) -> bool:
    return bool(_impl().user_has_openrouter_key(user_id))


def set_user_openrouter_key(user_id: str, api_key: str):
    return _impl().set_user_openrouter_key(user_id, api_key)


def clear_user_openrouter_key(user_id: str):
    return _impl().clear_user_openrouter_key(user_id)


def reserve_generation(user_id: str, *, estimated_tokens: int = 25_000):
    return _impl().reserve_generation(user_id, estimated_tokens=estimated_tokens)


def record_llm_usage(**kwargs):
    return _impl().record_llm_usage(**kwargs)


def upsert_job(**kwargs):
    return _impl().upsert_job(**kwargs)


def save_job_state(**kwargs):
    return _impl().save_job_state(**kwargs)


def get_job_state(job_id: str, user_id: str):
    return _impl().get_job_state(job_id, user_id)


def list_user_jobs(user_id: str, *, limit: int = 50):
    return _impl().list_user_jobs(user_id, limit=limit)


def sync_job_storage(**kwargs):
    return _impl().sync_job_storage(**kwargs)


def delete_job(**kwargs):
    return _impl().delete_job(**kwargs)

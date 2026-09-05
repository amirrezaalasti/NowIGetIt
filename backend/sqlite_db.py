"""SQLite + local files: free persistence without Supabase.

Videos and documents stay under ARTIFACTS_ROOT. Account, job index, and
usage live in a SQLite file next to them (`_local/nowigetit.db`).
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

_LOCK = threading.Lock()
_state: dict[str, Any] = {"path": None, "conn": None}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY,
  email TEXT,
  name TEXT,
  image_url TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  prompt TEXT,
  title TEXT,
  status TEXT,
  meta_json TEXT,
  plan_json TEXT,
  events_json TEXT,
  storage_bytes INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_jobs_user_created
  ON jobs(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS monthly_usage (
  user_id TEXT NOT NULL,
  period_start TEXT NOT NULL,
  requests_used INTEGER NOT NULL DEFAULT 0,
  tokens_used INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (user_id, period_start)
);

CREATE TABLE IF NOT EXISTS llm_usage (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id TEXT NOT NULL,
  job_id TEXT,
  kind TEXT,
  model TEXT,
  tokens_in INTEGER NOT NULL DEFAULT 0,
  tokens_out INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _period_start() -> str:
    return datetime.now(timezone.utc).replace(day=1).date().isoformat()


def _db_path() -> Path:
    from backend.artifacts import artifacts_root

    root = artifacts_root() / "_local"
    root.mkdir(parents=True, exist_ok=True)
    return root / "nowigetit.db"


def close() -> None:
    with _LOCK:
        conn = _state.get("conn")
        if conn is not None:
            conn.close()
        _state["conn"] = None
        _state["path"] = None


def _dumps(value: Any) -> Optional[str]:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False)


def _loads(text: Optional[str], fallback: Any) -> Any:
    if not text:
        return fallback
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return fallback


def _migrate_json_users(conn: sqlite3.Connection) -> None:
    users_dir = _db_path().parent / "users"
    if not users_dir.is_dir():
        return
    for path in users_dir.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        user_id = str(data.get("user_id") or path.stem)
        profile = data.get("profile") if isinstance(data.get("profile"), dict) else {}
        now = _now()
        conn.execute(
            """
            INSERT INTO users (id, email, name, image_url, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO NOTHING
            """,
            (
                user_id,
                profile.get("email") or data.get("email"),
                profile.get("name") or data.get("name"),
                profile.get("image_url"),
                str(profile.get("created_at") or now),
                str(profile.get("updated_at") or now),
            ),
        )
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        period = str(usage.get("period_start") or _period_start())
        llm = usage.get("llm") if isinstance(usage.get("llm"), dict) else {}
        conn.execute(
            """
            INSERT INTO monthly_usage (user_id, period_start, requests_used, tokens_used)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id, period_start) DO NOTHING
            """,
            (
                user_id,
                period,
                int(llm.get("requests_used") or 0),
                int(llm.get("tokens_used") or 0),
            ),
        )
    conn.commit()


def _conn() -> sqlite3.Connection:
    path = str(_db_path())
    current = _state.get("conn")
    if current is not None and _state.get("path") == path:
        return current
    if current is not None:
        current.close()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.executescript(_SCHEMA)
    _migrate_json_users(conn)
    _state["conn"] = conn
    _state["path"] = path
    return conn


def ensure_user(
    *,
    user_id: str,
    email: Optional[str] = None,
    name: Optional[str] = None,
    image_url: Optional[str] = None,
) -> dict[str, Any]:
    now = _now()
    with _LOCK:
        conn = _conn()
        conn.execute(
            """
            INSERT INTO users (id, email, name, image_url, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              email = COALESCE(excluded.email, users.email),
              name = COALESCE(excluded.name, users.name),
              image_url = COALESCE(excluded.image_url, users.image_url),
              updated_at = excluded.updated_at
            """,
            (user_id, email, name, image_url, now, now),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(row) if row else {"id": user_id, "email": email, "name": name}


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


def _storage_bytes(conn: sqlite3.Connection, user_id: str) -> int:
    row = conn.execute(
        "SELECT COALESCE(SUM(storage_bytes), 0) FROM jobs WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    stored = int(row[0] if row else 0)
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
        conn = _conn()
        row = conn.execute(
            """
            SELECT requests_used, tokens_used FROM monthly_usage
            WHERE user_id = ? AND period_start = ?
            """,
            (user_id, period),
        ).fetchone()
        bytes_used = _storage_bytes(conn, user_id)
    usage = _empty_usage(user_id)
    if row:
        usage["llm"]["requests_used"] = int(row["requests_used"] or 0)
        usage["llm"]["tokens_used"] = int(row["tokens_used"] or 0)
    usage["storage"]["bytes_used"] = bytes_used
    return usage


def reserve_generation(user_id: str, *, estimated_tokens: int = 25_000) -> dict[str, Any]:
    del estimated_tokens
    period = _period_start()
    with _LOCK:
        conn = _conn()
        conn.execute(
            """
            INSERT INTO monthly_usage (user_id, period_start, requests_used, tokens_used)
            VALUES (?, ?, 1, 0)
            ON CONFLICT(user_id, period_start) DO UPDATE SET
              requests_used = monthly_usage.requests_used + 1
            """,
            (user_id, period),
        )
        conn.commit()
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
        conn = _conn()
        conn.execute(
            """
            INSERT INTO llm_usage (user_id, job_id, kind, model, tokens_in, tokens_out, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, job_id, kind, model, int(tokens_in or 0), int(tokens_out or 0), _now()),
        )
        conn.execute(
            """
            INSERT INTO monthly_usage (user_id, period_start, requests_used, tokens_used)
            VALUES (?, ?, 0, ?)
            ON CONFLICT(user_id, period_start) DO UPDATE SET
              tokens_used = monthly_usage.tokens_used + excluded.tokens_used
            """,
            (user_id, period, added),
        )
        conn.commit()


def upsert_job(
    *,
    job_id: str,
    user_id: str,
    prompt: Optional[str] = None,
    title: Optional[str] = None,
    status: str = "running",
) -> None:
    now = _now()
    with _LOCK:
        conn = _conn()
        conn.execute(
            """
            INSERT INTO jobs (
              id, user_id, prompt, title, status, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              user_id = excluded.user_id,
              prompt = COALESCE(excluded.prompt, jobs.prompt),
              title = COALESCE(excluded.title, jobs.title),
              status = excluded.status,
              updated_at = excluded.updated_at
            """,
            (job_id, user_id, prompt, title, status, now, now),
        )
        conn.commit()


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
    with _LOCK:
        conn = _conn()
        conn.execute(
            """
            INSERT INTO jobs (
              id, user_id, prompt, title, status, meta_json, plan_json, events_json,
              created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              user_id = excluded.user_id,
              prompt = COALESCE(excluded.prompt, jobs.prompt),
              title = COALESCE(excluded.title, jobs.title),
              status = COALESCE(excluded.status, jobs.status),
              meta_json = COALESCE(excluded.meta_json, jobs.meta_json),
              plan_json = COALESCE(excluded.plan_json, jobs.plan_json),
              events_json = COALESCE(excluded.events_json, jobs.events_json),
              updated_at = excluded.updated_at
            """,
            (
                job_id,
                user_id,
                prompt,
                title,
                status or "running",
                _dumps(meta),
                _dumps(plan),
                _dumps(events),
                created or now,
                now,
            ),
        )
        conn.commit()


def get_job_state(job_id: str, user_id: str) -> Optional[dict[str, Any]]:
    with _LOCK:
        conn = _conn()
        row = conn.execute(
            "SELECT * FROM jobs WHERE id = ? AND user_id = ?",
            (job_id, user_id),
        ).fetchone()
    if not row:
        return None
    return _job_payload(row)


def _job_payload(row: sqlite3.Row) -> dict[str, Any]:
    from backend.artifacts import artifacts_root

    root = artifacts_root() / row["id"]
    meta = _loads(row["meta_json"], None)
    return {
        "id": row["id"],
        "job_id": row["id"],
        "user_id": row["user_id"],
        "prompt": row["prompt"],
        "title": row["title"],
        "status": row["status"],
        "meta": meta,
        "plan": _loads(row["plan_json"], None),
        "events": _loads(row["events_json"], []),
        "created_at": row["created_at"],
        "has_result": (root / "result.json").exists(),
        "has_final_video": (root / "final.mp4").exists()
        or (root / "document.json").exists()
        or (root / "podcast.wav").exists()
        or (root / "quiz.json").exists()
        or (root / "interactive.json").exists(),
        "storage_bytes": int(row["storage_bytes"] or 0),
        "kind": (meta.get("kind") if isinstance(meta, dict) else None)
        or (
            "document"
            if row["id"].startswith("doc_")
            else "podcast"
            if row["id"].startswith("pod_")
            else "quiz"
            if row["id"].startswith("quiz_")
            else "interactive"
            if row["id"].startswith("lab_")
            else "video"
        ),
    }


def _index_disk_jobs(conn: sqlite3.Connection, user_id: str) -> None:
    from backend.artifacts import artifacts_root

    root = artifacts_root()
    if not root.exists():
        return
    now = _now()
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
        plan_path = path / "scene_plan.json"
        plan = None
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
        conn.execute(
            """
            INSERT INTO jobs (
              id, user_id, prompt, title, status, meta_json, plan_json,
              created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              prompt = COALESCE(excluded.prompt, jobs.prompt),
              title = COALESCE(excluded.title, jobs.title),
              status = COALESCE(excluded.status, jobs.status),
              meta_json = COALESCE(excluded.meta_json, jobs.meta_json),
              plan_json = COALESCE(excluded.plan_json, jobs.plan_json),
              updated_at = excluded.updated_at
            """,
            (
                path.name,
                user_id,
                meta.get("prompt") if isinstance(meta.get("prompt"), str) else None,
                title if isinstance(title, str) else None,
                status or "unknown",
                _dumps(meta),
                _dumps(plan) if isinstance(plan, dict) else None,
                str(meta.get("created_at") or now),
                now,
            ),
        )


def list_user_jobs(user_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
    with _LOCK:
        conn = _conn()
        _index_disk_jobs(conn, user_id)
        conn.commit()
        rows = conn.execute(
            """
            SELECT * FROM jobs
            WHERE user_id = ?
            ORDER BY created_at DESC, updated_at DESC
            LIMIT ?
            """,
            (user_id, max(int(limit), 1)),
        ).fetchall()
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
        conn = _conn()
        conn.execute(
            """
            UPDATE jobs SET storage_bytes = ?, updated_at = ?
            WHERE id = ? AND user_id = ?
            """,
            (size, _now(), job_id, user_id),
        )
        conn.commit()


def delete_job(*, job_id: str, user_id: str) -> None:
    with _LOCK:
        conn = _conn()
        conn.execute(
            "DELETE FROM jobs WHERE id = ? AND user_id = ?",
            (job_id, user_id),
        )
        conn.commit()

"""Supabase persistence: users, quotas, jobs, LLM/storage usage."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from backend.config import get_settings

logger = logging.getLogger(__name__)


class QuotaExceededError(Exception):
    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(detail)


def supabase_enabled() -> bool:
    get_settings()
    from backend.local_db import storage_mode

    return storage_mode() == "supabase"


def _is_unreachable(exc: BaseException) -> bool:
    text = f"{type(exc).__name__}: {exc}".lower()
    needles = (
        "name or service not known",
        "nodename nor servname",
        "connecterror",
        "connecttimeout",
        "failed to resolve",
        "could not resolve host",
        "getaddrinfo",
        "temporary failure in name resolution",
        "network is unreachable",
        "not installed",
        "supabase is not configured",
    )
    return any(needle in text for needle in needles)


def _client():
    try:
        # Import ClientOptions from the package root (SyncClientOptions). The
        # supabase.lib.client_options.ClientOptions class has no `.storage` and
        # crashes create_client on supabase-py 2.24+.
        from supabase import ClientOptions, create_client
    except ImportError as exc:
        raise RuntimeError("supabase package is not installed") from exc

    settings = get_settings()
    if not settings.supabase_url or not settings.supabase_service_role_key:
        raise RuntimeError("Supabase is not configured (SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY)")
    return create_client(
        settings.supabase_url,
        settings.supabase_service_role_key,
        options=ClientOptions(postgrest_client_timeout=8),
    )


def _rpc(name: str, params: dict[str, Any]) -> Any:
    try:
        return _client().rpc(name, params).execute().data
    except Exception as exc:  # noqa: BLE001
        message = str(exc)
        for code in ("LLM_REQUEST_LIMIT", "LLM_TOKEN_LIMIT", "STORAGE_LIMIT", "JOB_NOT_FOUND"):
            if code in message:
                raise QuotaExceededError(code, message) from exc
        if _is_unreachable(exc):
            logger.warning("Supabase unreachable during %s; continuing without it (%s)", name, exc)
            return None
        raise


def ensure_user(
    *,
    user_id: str,
    email: Optional[str] = None,
    name: Optional[str] = None,
    image_url: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    if not supabase_enabled():
        from backend.local_db import ensure_user as local_ensure

        return local_ensure(
            user_id=user_id,
            email=email,
            name=name,
            image_url=image_url,
        )
    return _rpc(
        "ensure_user",
        {
            "p_id": user_id,
            "p_email": email,
            "p_name": name,
            "p_image_url": image_url,
        },
    )


def get_user_usage(user_id: str) -> Optional[dict[str, Any]]:
    if not supabase_enabled():
        from backend.local_db import get_user_usage as local_usage

        return local_usage(user_id)
    try:
        data = _rpc("get_user_usage", {"p_user_id": user_id})
        return data if isinstance(data, dict) else None
    except Exception:  # noqa: BLE001
        logger.exception("get_user_usage failed for %s", user_id)
        return None


def get_user_openrouter_key(user_id: str) -> Optional[str]:
    """Prefer local/mongo store; Supabase mode falls back to local for BYOK."""
    from backend.local_db import get_user_openrouter_key as local_get

    return local_get(user_id)


def user_has_openrouter_key(user_id: str) -> bool:
    from backend.local_db import user_has_openrouter_key as local_has

    return bool(local_has(user_id))


def set_user_openrouter_key(user_id: str, api_key: str) -> dict[str, Any]:
    from backend.local_db import set_user_openrouter_key as local_set

    return local_set(user_id, api_key)


def clear_user_openrouter_key(user_id: str) -> dict[str, Any]:
    from backend.local_db import clear_user_openrouter_key as local_clear

    return local_clear(user_id)


def openrouter_key_status(user_id: str) -> dict[str, Any]:
    from backend.user_secrets import key_fingerprint, mask_api_key

    plain = get_user_openrouter_key(user_id)
    if not plain:
        return {"configured": False, "masked_key": None, "fingerprint": None}
    return {
        "configured": True,
        "masked_key": mask_api_key(plain),
        "fingerprint": key_fingerprint(plain),
    }


def reserve_generation(user_id: str, *, estimated_tokens: int = 25_000) -> Optional[dict[str, Any]]:
    """Atomically check quotas and increment monthly generation count."""
    if not supabase_enabled():
        from backend.local_db import reserve_generation as local_reserve

        return local_reserve(user_id, estimated_tokens=estimated_tokens)
    data = _rpc(
        "reserve_generation",
        {"p_user_id": user_id, "p_estimated_tokens": estimated_tokens},
    )
    return data if isinstance(data, dict) else None


def assert_within_quotas(user_id: str, *, need_tokens: int = 1) -> Optional[dict[str, Any]]:
    """Read-only quota gate (e.g. retouch) — does not consume a generation slot."""
    usage = get_user_usage(user_id)
    if not usage:
        return None
    llm = usage.get("llm") or {}
    storage = usage.get("storage") or {}
    tokens_used = int(llm.get("tokens_used") or 0)
    tokens_limit = int(llm.get("tokens_limit") or 0)
    storage_used = int(storage.get("bytes_used") or 0)
    storage_limit = int(storage.get("bytes_limit") or 0)
    if tokens_limit and tokens_used + max(need_tokens, 0) > tokens_limit:
        raise QuotaExceededError(
            "LLM_TOKEN_LIMIT",
            f"Monthly LLM token limit reached ({tokens_used}/{tokens_limit})",
        )
    if storage_limit and storage_used >= storage_limit:
        raise QuotaExceededError(
            "STORAGE_LIMIT",
            f"Storage limit reached ({storage_used}/{storage_limit} bytes)",
        )
    return usage


def upsert_job(
    *,
    job_id: str,
    user_id: str,
    prompt: Optional[str] = None,
    title: Optional[str] = None,
    status: str = "running",
) -> None:
    if not supabase_enabled():
        from backend.local_db import upsert_job as local_upsert

        local_upsert(
            job_id=job_id,
            user_id=user_id,
            prompt=prompt,
            title=title,
            status=status,
        )
        return
    _rpc(
        "upsert_job",
        {
            "p_id": job_id,
            "p_user_id": user_id,
            "p_prompt": prompt,
            "p_title": title,
            "p_status": status,
        },
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
    """Persist durable job payload (survives ephemeral /tmp)."""
    if not supabase_enabled():
        from backend.local_db import save_job_state as local_save

        local_save(
            job_id=job_id,
            user_id=user_id,
            prompt=prompt,
            title=title,
            status=status,
            meta=meta,
            plan=plan,
            events=events,
        )
        return
    try:
        _rpc(
            "save_job_state",
            {
                "p_id": job_id,
                "p_user_id": user_id,
                "p_prompt": prompt,
                "p_title": title,
                "p_status": status,
                "p_meta": meta,
                "p_plan": plan,
                "p_events": events,
            },
        )
    except Exception:  # noqa: BLE001
        logger.exception("Failed to save job state for %s", job_id)


def get_job_state(job_id: str, user_id: str) -> Optional[dict[str, Any]]:
    if not supabase_enabled():
        from backend.local_db import get_job_state as local_get

        return local_get(job_id, user_id)
    try:
        data = _rpc("get_job_state", {"p_id": job_id, "p_user_id": user_id})
    except Exception:  # noqa: BLE001
        logger.exception("Failed to load job state for %s", job_id)
        return None
    return data if isinstance(data, dict) else None


def list_user_jobs(user_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
    if not supabase_enabled():
        from backend.local_db import list_user_jobs as local_list

        return local_list(user_id, limit=limit)
    try:
        data = _rpc("list_user_jobs", {"p_user_id": user_id, "p_limit": limit})
    except Exception:  # noqa: BLE001
        logger.exception("Failed to list jobs for user %s", user_id)
        return []
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    return []


def record_llm_usage(
    *,
    user_id: str,
    job_id: Optional[str],
    kind: str,
    model: Optional[str],
    tokens_in: int = 0,
    tokens_out: int = 0,
    meta: Optional[dict[str, Any]] = None,
) -> None:
    if not supabase_enabled():
        from backend.local_db import record_llm_usage as local_record

        local_record(
            user_id=user_id,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            job_id=job_id,
            kind=kind,
            model=model,
        )
        return
    if tokens_in <= 0 and tokens_out <= 0:
        return
    _rpc(
        "record_llm_usage",
        {
            "p_user_id": user_id,
            "p_job_id": job_id,
            "p_kind": kind,
            "p_model": model,
            "p_tokens_in": tokens_in,
            "p_tokens_out": tokens_out,
            "p_meta": meta or {},
        },
    )


def flush_client_usage(
    *,
    user_id: str,
    job_id: Optional[str],
    usage_log: list[dict[str, Any]],
) -> None:
    if not usage_log:
        return
    for entry in usage_log:
        try:
            record_llm_usage(
                user_id=user_id,
                job_id=job_id,
                kind=str(entry.get("kind") or "llm"),
                model=entry.get("model"),
                tokens_in=int(entry.get("tokens_in") or 0),
                tokens_out=int(entry.get("tokens_out") or 0),
                meta=entry.get("meta") if isinstance(entry.get("meta"), dict) else {},
            )
        except Exception:  # noqa: BLE001
            logger.exception("Failed to record LLM usage for user %s", user_id)


def directory_size_bytes(path: Path) -> int:
    total = 0
    if not path.exists():
        return 0
    for p in path.rglob("*"):
        if p.is_file():
            try:
                total += p.stat().st_size
            except OSError:
                continue
    return total


def sync_job_storage(*, user_id: str, job_id: str, job_path: Path) -> None:
    if not supabase_enabled():
        from backend.local_db import sync_job_storage as local_sync

        local_sync(user_id=user_id, job_id=job_id, job_path=job_path)
        return
    size = directory_size_bytes(job_path)
    try:
        _rpc(
            "set_job_storage",
            {
                "p_user_id": user_id,
                "p_job_id": job_id,
                "p_storage_bytes": size,
            },
        )
    except QuotaExceededError:
        raise
    except Exception:  # noqa: BLE001
        logger.exception("Failed to sync storage for job %s", job_id)


def delete_job(*, job_id: str, user_id: str) -> None:
    """Remove durable job row (releases storage)."""
    if not supabase_enabled():
        from backend.local_db import delete_job as local_delete

        local_delete(job_id=job_id, user_id=user_id)
        return
    try:
        _rpc("delete_job", {"p_id": job_id, "p_user_id": user_id})
    except Exception:  # noqa: BLE001
        logger.exception("Failed to delete job row %s via delete_job RPC", job_id)
        raise

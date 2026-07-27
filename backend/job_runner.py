"""Process-level job registry so pipelines keep running after SSE clients disconnect."""

from __future__ import annotations

import asyncio
import json
import threading
import time
from collections.abc import AsyncIterator, Callable, Iterator
from pathlib import Path
from typing import Any, Optional

from backend import artifacts as store

_lock = threading.RLock()
_threads: dict[str, threading.Thread] = {}
_errors: dict[str, str] = {}


def is_running(job_id: str) -> bool:
    with _lock:
        t = _threads.get(job_id)
        return bool(t and t.is_alive())


def last_error(job_id: str) -> Optional[str]:
    with _lock:
        return _errors.get(job_id)


def event_count(job_id: str) -> int:
    path = store.job_dir(job_id) / "events.jsonl"
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def read_events(job_id: str) -> list[dict[str, Any]]:
    path = store.job_dir(job_id) / "events.jsonl"
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def start_job(job_id: str, target: Callable[[], None]) -> bool:
    """
    Start a daemon worker for job_id if none is alive.
    Returns True if a new thread was started, False if already running.
    """
    with _lock:
        existing = _threads.get(job_id)
        if existing and existing.is_alive():
            return False
        _errors.pop(job_id, None)

        def wrapper() -> None:
            try:
                target()
            except Exception as exc:  # noqa: BLE001
                with _lock:
                    _errors[job_id] = str(exc)
                # Persist error so reconnecting clients see it.
                try:
                    store.append_event(
                        job_id,
                        {
                            "type": "error",
                            "message": str(exc),
                            "data": {"error": str(exc), "job_id": job_id},
                        },
                    )
                except Exception:  # noqa: BLE001
                    pass
            finally:
                with _lock:
                    cur = _threads.get(job_id)
                    if cur is threading.current_thread():
                        _threads.pop(job_id, None)

        thread = threading.Thread(
            target=wrapper,
            name=f"nowigetit-job-{job_id}",
            daemon=True,
        )
        _threads[job_id] = thread
        thread.start()
        return True


def iter_event_tail(
    job_id: str,
    *,
    after: int = 0,
    poll_seconds: float = 0.45,
    idle_rounds_after_stop: int = 4,
) -> Iterator[dict[str, Any]]:
    """
    Yield event dicts from events.jsonl starting at index `after`.
    Keeps polling while the job thread is alive; stops shortly after it ends
    once no new events appear (or after terminal complete/error).
    """
    idx = max(0, after)
    idle = 0
    while True:
        events = read_events(job_id)
        progressed = False
        while idx < len(events):
            ev = events[idx]
            idx += 1
            progressed = True
            idle = 0
            yield ev
            et = str(ev.get("type") or "")
            if et in {"complete", "error"} and not is_running(job_id):
                return
        if progressed:
            continue
        running = is_running(job_id)
        if not running:
            idle += 1
            # Surface a late worker error if events file never got it.
            err = last_error(job_id)
            if err and idle == 1:
                yield {
                    "type": "error",
                    "message": err,
                    "data": {"error": err, "job_id": job_id},
                }
                return
            if idle >= idle_rounds_after_stop:
                return
        time.sleep(poll_seconds)


async def aiter_event_tail(
    job_id: str,
    *,
    after: int = 0,
    poll_seconds: float = 0.45,
    idle_rounds_after_stop: int = 4,
) -> AsyncIterator[dict[str, Any]]:
    """
    Async variant of iter_event_tail — uses asyncio.sleep so SSE streaming does
    not pin a Starlette/anyio threadpool worker during idle polls.
    """
    idx = max(0, after)
    idle = 0
    while True:
        events = await asyncio.to_thread(read_events, job_id)
        progressed = False
        while idx < len(events):
            ev = events[idx]
            idx += 1
            progressed = True
            idle = 0
            yield ev
            et = str(ev.get("type") or "")
            if et in {"complete", "error"} and not is_running(job_id):
                return
        if progressed:
            continue
        running = is_running(job_id)
        if not running:
            idle += 1
            err = last_error(job_id)
            if err and idle == 1:
                yield {
                    "type": "error",
                    "message": err,
                    "data": {"error": err, "job_id": job_id},
                }
                return
            if idle >= idle_rounds_after_stop:
                return
        await asyncio.sleep(poll_seconds)


def job_status(job_id: str) -> dict[str, Any]:
    """Lightweight status for UI hydration."""
    root = Path(store.job_dir(job_id))
    has_result = (root / "result.json").exists()
    has_final = (root / "final.mp4").exists()
    has_plan = (root / "scene_plan.json").exists()
    running = is_running(job_id)

    scenes_root = root / "scenes"
    scene_work = False
    if scenes_root.exists():
        for sdir in scenes_root.iterdir():
            if not sdir.is_dir():
                continue
            if (sdir / "code_final.py").exists() or (sdir / "scene.mp4").exists():
                scene_work = True
                break

    if has_result or has_final:
        status = "complete"
    elif running:
        status = "running"
    elif scene_work:
        status = "interrupted"
    elif has_plan:
        status = "awaiting_plan"
    else:
        status = "unknown"

    return {
        "job_id": job_id,
        "status": status,
        "running": running,
        "event_count": event_count(job_id),
        "has_result": has_result,
        "has_final_video": has_final,
        "error": last_error(job_id),
    }

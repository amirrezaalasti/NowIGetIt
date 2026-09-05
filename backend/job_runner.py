"""Process-level job registry so pipelines keep running after SSE clients disconnect.

Work for one job is split into independently schedulable *tasks*: the main
``pipeline`` task plus one ``scene:<scene_id>`` task per in-flight scene edit.
That is what lets a user retouch scene 1 while scene 4 is still generating, and
retouch scenes 1 and 2 at the same time.

Tasks run concurrently, so anything they share is guarded here:
  * ``scene_lock``   — one writer at a time per scene folder (code revisions,
                       renders, published clips).
  * ``compose_lock`` — one writer at a time for the job's final.mp4.
  * ``plan_lock``    — read-modify-write of scene_plan.json.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Optional

from backend import artifacts as store

#: Task key for the whole-job generation pipeline.
PIPELINE_TASK = "pipeline"

_lock = threading.RLock()
_threads: dict[tuple[str, str], threading.Thread] = {}
_errors: dict[str, str] = {}
_task_errors: dict[tuple[str, str], str] = {}
_cancelled: set[str] = set()

# Shared-resource locks, created lazily and keyed by resource name.
_res_locks: dict[str, threading.RLock] = {}
# job_id → {scene_id: depth} for every scene currently held by a writer.
_busy_scenes: dict[str, dict[str, int]] = {}


class SceneBusyError(RuntimeError):
    """Raised when a scene is already being generated or edited."""


def scene_task_key(scene_id: str) -> str:
    return f"scene:{scene_id}"


def cancel_job(job_id: str) -> None:
    with _lock:
        _cancelled.add(job_id)


def is_cancelled(job_id: str) -> bool:
    with _lock:
        return job_id in _cancelled


def is_task_running(job_id: str, task_key: str) -> bool:
    with _lock:
        t = _threads.get((job_id, task_key))
        return bool(t and t.is_alive())


def is_pipeline_running(job_id: str) -> bool:
    """True only for the whole-job generation pipeline (not scene edits)."""
    return is_task_running(job_id, PIPELINE_TASK)


def is_running(job_id: str) -> bool:
    """True while *any* task for this job is alive (pipeline or scene edit)."""
    with _lock:
        return any(
            t.is_alive() for (jid, _), t in _threads.items() if jid == job_id
        )


def active_tasks(job_id: str) -> list[str]:
    with _lock:
        return sorted(
            key for (jid, key), t in _threads.items() if jid == job_id and t.is_alive()
        )


def _error_file(job_id: str) -> Path:
    return Path(store.job_dir(job_id)) / "last_error.txt"


def last_error(job_id: str) -> Optional[str]:
    """Last unhandled error from the job's main pipeline task."""
    with _lock:
        mem = _errors.get(job_id)
    if mem:
        return mem
    path = _error_file(job_id)
    try:
        if path.exists():
            text = path.read_text(encoding="utf-8").strip()
            return text or None
    except OSError:
        return None
    return None


def _clear_persisted_error(job_id: str) -> None:
    path = _error_file(job_id)
    try:
        if path.exists():
            path.unlink()
    except OSError:
        pass


def _persist_error(job_id: str, message: str) -> None:
    try:
        _error_file(job_id).write_text(message, encoding="utf-8")
    except OSError:
        pass


def task_error(job_id: str, task_key: str) -> Optional[str]:
    with _lock:
        return _task_errors.get((job_id, task_key))


# ── Shared-resource locks ────────────────────────────────────────────────────


def _resource_lock(name: str) -> threading.RLock:
    with _lock:
        existing = _res_locks.get(name)
        if existing is None:
            existing = threading.RLock()
            _res_locks[name] = existing
        return existing


@contextmanager
def scene_lock(
    job_id: str,
    scene_id: str,
    *,
    timeout: Optional[float] = None,
) -> Iterator[None]:
    """Exclusive writer access to one scene's artifacts.

    Different scenes never contend, so parallel edits stay parallel. Pass a
    ``timeout`` to fail fast with :class:`SceneBusyError` instead of queueing
    behind a multi-minute generation.
    """
    lock = _resource_lock(f"scene::{job_id}::{scene_id}")
    acquired = lock.acquire(True, timeout) if timeout is not None else lock.acquire()
    if not acquired:
        raise SceneBusyError(
            f"Scene {scene_id} is already being generated or edited."
        )
    with _lock:
        counts = _busy_scenes.setdefault(job_id, {})
        counts[scene_id] = counts.get(scene_id, 0) + 1
    try:
        yield
    finally:
        with _lock:
            counts = _busy_scenes.get(job_id) or {}
            remaining = counts.get(scene_id, 1) - 1
            if remaining > 0:
                counts[scene_id] = remaining
            else:
                counts.pop(scene_id, None)
            if not counts:
                _busy_scenes.pop(job_id, None)
        lock.release()


@contextmanager
def compose_lock(job_id: str) -> Iterator[None]:
    """Exclusive access to the job's final.mp4 and its ffmpeg scratch files."""
    lock = _resource_lock(f"compose::{job_id}")
    lock.acquire()
    try:
        yield
    finally:
        lock.release()


@contextmanager
def plan_lock(job_id: str) -> Iterator[None]:
    """Exclusive access for read-modify-write cycles on scene_plan.json."""
    lock = _resource_lock(f"plan::{job_id}")
    lock.acquire()
    try:
        yield
    finally:
        lock.release()


def busy_scenes(job_id: str) -> list[str]:
    with _lock:
        return sorted((_busy_scenes.get(job_id) or {}).keys())


def is_scene_busy(job_id: str, scene_id: str) -> bool:
    with _lock:
        return scene_id in (_busy_scenes.get(job_id) or {})


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


def start_task(
    job_id: str,
    task_key: str,
    target: Callable[[], None],
) -> bool:
    """
    Start a daemon worker for (job_id, task_key) if none is alive.
    Returns True if a new thread was started, False if that task already runs.

    Tasks with different keys run concurrently — that is how a scene edit
    proceeds while the main pipeline is still building later scenes.
    """
    key = (job_id, task_key)
    with _lock:
        existing = _threads.get(key)
        if existing and existing.is_alive():
            return False
        _task_errors.pop(key, None)
        if task_key == PIPELINE_TASK:
            _errors.pop(job_id, None)
            _clear_persisted_error(job_id)
            # Only a fresh pipeline run clears a cancel: a scene edit starting
            # mid-cancel must not resurrect the job.
            _cancelled.discard(job_id)

        def wrapper() -> None:
            try:
                target()
            except Exception as exc:  # noqa: BLE001
                with _lock:
                    _task_errors[key] = str(exc)
                    if task_key == PIPELINE_TASK:
                        _errors[job_id] = str(exc)
                if task_key == PIPELINE_TASK:
                    _persist_error(job_id, str(exc))
                # Persist pipeline errors so reconnecting clients see them.
                # Scene-edit errors stay on their own stream — appending them
                # here would terminate every client tailing the job log.
                if task_key == PIPELINE_TASK:
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
                    cur = _threads.get(key)
                    if cur is threading.current_thread():
                        _threads.pop(key, None)

        thread = threading.Thread(
            target=wrapper,
            name=f"nowigetit-job-{job_id}-{task_key}",
            daemon=True,
        )
        _threads[key] = thread
        thread.start()
        return True


def start_job(job_id: str, target: Callable[[], None]) -> bool:
    """Start the job's main generation pipeline task."""
    return start_task(job_id, PIPELINE_TASK, target)


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
    pipeline_running = is_pipeline_running(job_id)
    err = last_error(job_id)

    scenes_root = root / "scenes"
    has_code = False
    has_clip = False
    if scenes_root.exists():
        for sdir in scenes_root.iterdir():
            if not sdir.is_dir():
                continue
            if (sdir / "code_final.py").exists():
                has_code = True
            if (sdir / "scene.mp4").exists() or (sdir / "scene_vo.mp4").exists():
                has_clip = True

    # Host-authored MCP writes code_final.py *before* render. That is not a
    # crashed pipeline — it is waiting to be rendered.
    if has_result or has_final:
        status = "complete"
    elif pipeline_running:
        status = "running"
    elif err:
        status = "error"
    elif has_clip:
        status = "interrupted"
    elif has_code and has_plan:
        status = "awaiting_render"
    elif has_plan:
        status = "awaiting_plan"
    else:
        status = "unknown"

    return {
        "job_id": job_id,
        "status": status,
        # `running` stays "is the main pipeline building scenes" so restore
        # logic doesn't reattach a finished job just because a scene edit runs.
        "running": pipeline_running,
        "any_task_running": running,
        "active_tasks": active_tasks(job_id),
        "busy_scenes": busy_scenes(job_id),
        "event_count": event_count(job_id),
        "has_result": has_result,
        "has_final_video": has_final,
        "error": err,
    }

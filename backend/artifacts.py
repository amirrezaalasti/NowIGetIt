"""Persistent job artifacts for debugging (plans, VLM frames, reviews, code)."""

from __future__ import annotations

import base64
import json
import logging
import os
import shutil
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from backend import supabase_db as db

ROOT = Path(__file__).resolve().parent.parent
_EVENT_LOCK = threading.Lock()
logger = logging.getLogger(__name__)


def artifacts_root() -> Path:
    """
    Local: repo/artifacts. On Vercel the deploy FS is read-only, so use /tmp.
    Note: /tmp is ephemeral per instance — durable ownership/usage lives in Supabase.
    """
    override = (os.getenv("ARTIFACTS_ROOT") or "").strip()
    if override:
        root = Path(override)
    elif os.getenv("VERCEL"):
        root = Path("/tmp/nowigetit/artifacts")
    else:
        root = ROOT / "artifacts"
    root.mkdir(parents=True, exist_ok=True)
    return root


def job_dir(job_id: str) -> Path:
    path = artifacts_root() / job_id
    path.mkdir(parents=True, exist_ok=True)
    (path / "scenes").mkdir(exist_ok=True)
    return path


def scene_dir(job_id: str, scene_id: str) -> Path:
    path = job_dir(job_id) / "scenes" / scene_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_json(path: Path, data: Any) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return str(path)


def _read_json_file(path: Path) -> Optional[Any]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _read_events_list(job_id: str) -> list[dict[str, Any]]:
    path = artifacts_root() / job_id / "events.jsonl"
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            events.append(item)
    return events


def sync_job_state(
    job_id: str,
    *,
    status: Optional[str] = None,
) -> None:
    """Mirror local meta/plan/events into Supabase for durable Vercel jobs."""
    if not db.supabase_enabled():
        return
    root = artifacts_root() / job_id
    meta = _read_json_file(root / "meta.json")
    if not isinstance(meta, dict):
        return
    user_id = meta.get("user_id")
    if not isinstance(user_id, str) or not user_id:
        return
    plan = _read_json_file(root / "scene_plan.json")
    plan_dict = plan if isinstance(plan, dict) else None
    title = None
    if plan_dict and isinstance(plan_dict.get("title"), str):
        title = plan_dict["title"]
    prompt = meta.get("prompt") if isinstance(meta.get("prompt"), str) else None
    events = _read_events_list(job_id)
    db.save_job_state(
        job_id=job_id,
        user_id=user_id,
        prompt=prompt,
        title=title,
        status=status,
        meta=meta,
        plan=plan_dict,
        events=events,
    )


def hydrate_job_from_db(job_id: str, user_id: str) -> bool:
    """Rebuild local job folder from SQLite/Supabase when files were wiped."""
    row = db.get_job_state(job_id, user_id)
    if not row:
        return False

    root = job_dir(job_id)
    meta = row.get("meta") if isinstance(row.get("meta"), dict) else None
    if not meta:
        meta = {
            "job_id": job_id,
            "prompt": row.get("prompt") or "",
            "created_at": row.get("created_at"),
            "settings": {},
            "user_id": user_id,
        }
    else:
        meta = {**meta, "user_id": user_id, "job_id": job_id}
    write_json(root / "meta.json", meta)

    plan = row.get("plan")
    if isinstance(plan, dict):
        write_json(root / "scene_plan.json", plan)
        for scene in plan.get("scenes") or []:
            if isinstance(scene, dict) and isinstance(scene.get("id"), str):
                write_json(scene_dir(job_id, scene["id"]) / "section.json", scene)

    events = row.get("events")
    if isinstance(events, list) and events:
        lines = [
            json.dumps(ev, ensure_ascii=False)
            for ev in events
            if isinstance(ev, dict)
        ]
        (root / "events.jsonl").write_text(
            ("\n".join(lines) + "\n") if lines else "",
            encoding="utf-8",
        )
    logger.info("Hydrated job %s from Supabase for user %s", job_id, user_id)
    return True


def append_event(job_id: str, event: dict[str, Any]) -> None:
    path = job_dir(job_id) / "events.jsonl"
    line = json.dumps(event, ensure_ascii=False) + "\n"
    with _EVENT_LOCK:
        with path.open("a", encoding="utf-8") as f:
            f.write(line)
        # Durable copy for reconnects across Vercel instances.
        try:
            sync_job_state(job_id)
        except Exception:  # noqa: BLE001
            logger.exception("Failed syncing events for job %s", job_id)


def init_job(
    job_id: str,
    *,
    prompt: str,
    settings_snapshot: dict[str, Any],
    user_id: Optional[str] = None,
    user_email: Optional[str] = None,
    user_name: Optional[str] = None,
) -> Path:
    root = job_dir(job_id)
    write_json(
        root / "meta.json",
        {
            "job_id": job_id,
            "prompt": prompt,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "settings": settings_snapshot,
            "user_id": user_id,
            "user_email": user_email,
            "user_name": user_name,
        },
    )
    if user_id:
        sync_job_state(job_id, status="running")
    return root


def job_owner_id(job_id: str) -> Optional[str]:
    meta_path = artifacts_root() / job_id / "meta.json"
    if not meta_path.exists():
        return None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    owner = meta.get("user_id")
    return owner if isinstance(owner, str) and owner else None


def assert_job_owner(job_id: str, user_id: str) -> None:
    """Raise FileNotFoundError if missing, PermissionError if not owned by user."""
    root = artifacts_root() / job_id
    if not root.exists() or not (root / "meta.json").exists():
        if not hydrate_job_from_db(job_id, user_id):
            raise FileNotFoundError(job_id)
    owner = job_owner_id(job_id)
    # Legacy jobs without owner are inaccessible once auth is on
    if owner != user_id:
        raise PermissionError(job_id)


def save_scene_plan(job_id: str, plan: dict[str, Any]) -> str:
    path = write_json(job_dir(job_id) / "scene_plan.json", plan)
    sync_job_state(job_id)
    return path


def save_scene_section(job_id: str, scene_id: str, section: dict[str, Any]) -> str:
    return write_json(scene_dir(job_id, scene_id) / "section.json", section)


def save_code(job_id: str, scene_id: str, code: str, *, revision: int) -> str:
    path = scene_dir(job_id, scene_id) / f"code_r{revision}.py"
    path.write_text(code, encoding="utf-8")
    final = scene_dir(job_id, scene_id) / "code_final.py"
    final.write_text(code, encoding="utf-8")
    return str(path)


def load_code(job_id: str, scene_id: str) -> Optional[str]:
    path = scene_dir(job_id, scene_id) / "code_final.py"
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8").strip()
    return text or None


def save_vlm_review(
    job_id: str,
    scene_id: str,
    *,
    revision: int,
    review: dict[str, Any],
    frame_path: Optional[str],
    frame_source: str,
) -> dict[str, Optional[str]]:
    """Persist VLM review JSON and a copy of the frame the model saw."""
    sdir = scene_dir(job_id, scene_id)
    review_path = sdir / f"vlm_r{revision}.json"
    stored_frame: Optional[str] = None

    if frame_path and Path(frame_path).exists():
        ext = Path(frame_path).suffix or ".png"
        dest = sdir / f"vlm_r{revision}_frame{ext}"
        shutil.copy2(frame_path, dest)
        stored_frame = str(dest)

    payload = {
        **review,
        "revision": revision,
        "frame_source": frame_source,
        "frame_path": stored_frame,
        "original_frame_path": frame_path,
    }
    write_json(review_path, payload)
    return {
        "review_path": str(review_path),
        "frame_path": stored_frame,
        "frame_url": (
            f"/api/jobs/{job_id}/file/scenes/{scene_id}/{Path(stored_frame).name}"
            if stored_frame
            else None
        ),
    }


def save_final_debug(job_id: str, data: dict[str, Any]) -> str:
    return write_json(job_dir(job_id) / "final_debug.json", data)


def _faststart_copy(src: Path, dest: Path) -> bool:
    """Remux mp4 with moov at the front so browsers can play while downloading."""
    if not shutil.which("ffmpeg"):
        shutil.copy2(src, dest)
        return dest.exists()
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Write to a temp file then replace — avoids serving a half-written mp4.
    tmp = dest.with_suffix(".tmp.mp4")
    try:
        import subprocess

        proc = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(src),
                "-c",
                "copy",
                "-movflags",
                "+faststart",
                str(tmp),
            ],
            capture_output=True,
            timeout=120,
        )
        if proc.returncode == 0 and tmp.exists() and tmp.stat().st_size > 0:
            tmp.replace(dest)
            return True
    except Exception:  # noqa: BLE001
        pass
    if tmp.exists():
        tmp.unlink(missing_ok=True)
    shutil.copy2(src, dest)
    return dest.exists()


def publish_scene_video(
    job_id: str,
    scene_id: str,
    video_path: Optional[str],
) -> Optional[str]:
    """Publish a web-playable scene.mp4 (faststart) into the artifact folder."""
    if not video_path or not Path(video_path).exists():
        return None
    dest = scene_dir(job_id, scene_id) / "scene.mp4"
    if not _faststart_copy(Path(video_path), dest):
        return None
    return f"/api/jobs/{job_id}/file/scenes/{scene_id}/scene.mp4"


def save_result(job_id: str, data: dict[str, Any]) -> str:
    return write_json(job_dir(job_id) / "result.json", data)


def job_kind(job_id: str, meta: Optional[dict[str, Any]] = None) -> str:
    """video | document | source | podcast | quiz | interactive."""
    if isinstance(meta, dict):
        kind = str(meta.get("kind") or "").strip()
        if kind:
            return kind
    if job_id.startswith("doc_"):
        return "document"
    if job_id.startswith("src_"):
        return "source"
    if job_id.startswith("pod_"):
        return "podcast"
    if job_id.startswith("quiz_"):
        return "quiz"
    if job_id.startswith("lab_"):
        return "interactive"
    return "video"


def _summarize_job_row(row: dict[str, Any], *, user_id: Optional[str] = None) -> dict[str, Any]:
    job_id = str(row.get("job_id") or row.get("id") or "")
    meta = row.get("meta") if isinstance(row.get("meta"), dict) else None
    kind = job_kind(job_id, meta)
    return {
        "job_id": job_id,
        "title": row.get("title"),
        "prompt": row.get("prompt"),
        "created_at": row.get("created_at"),
        "has_result": bool(row.get("has_result")),
        "has_final_video": bool(row.get("has_final_video")),
        "user_id": row.get("user_id") or user_id,
        "status": row.get("status"),
        "kind": kind,
    }


def _is_source_job(job_id: str, kind: str) -> bool:
    return kind == "source" or job_id.startswith("src_")


def list_jobs(
    limit: int = 50,
    *,
    user_id: Optional[str] = None,
    include_sources: bool = False,
) -> list[dict[str, Any]]:
    if user_id:
        fetch_limit = limit if include_sources else max(limit * 2, 40)
        rows = db.list_user_jobs(user_id, limit=fetch_limit)
        if rows:
            jobs: list[dict[str, Any]] = []
            for row in rows:
                if not (row.get("job_id") or row.get("id")):
                    continue
                summary = _summarize_job_row(row, user_id=user_id)
                if not include_sources and _is_source_job(
                    str(summary.get("job_id") or ""), str(summary.get("kind") or "")
                ):
                    continue
                jobs.append(summary)
                if len(jobs) >= limit:
                    break
            if jobs:
                return jobs

    root = artifacts_root()
    if not root.exists():
        return []
    jobs: list[dict[str, Any]] = []
    for path in sorted(root.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not path.is_dir() or path.name.startswith((".", "_")):
            continue
        meta_path = path / "meta.json"
        meta: dict[str, Any] = {"job_id": path.name}
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass
        if user_id is not None and meta.get("user_id") != user_id:
            continue
        plan_path = path / "scene_plan.json"
        title = meta.get("title") if isinstance(meta.get("title"), str) else None
        if plan_path.exists():
            try:
                title = json.loads(plan_path.read_text(encoding="utf-8")).get("title") or title
            except json.JSONDecodeError:
                pass
        has_result = (path / "result.json").exists()
        has_final_video = (
            (path / "final.mp4").exists()
            or (path / "podcast.wav").exists()
            or (path / "podcast.mp3").exists()
        )
        kind = job_kind(path.name, meta)
        if not include_sources and _is_source_job(path.name, kind):
            continue
        if has_result or has_final_video:
            status = "complete"
        elif str(meta.get("status") or "").strip():
            status = str(meta.get("status"))
        elif (path / "scene_plan.json").exists():
            status = "awaiting_plan"
        else:
            status = "unknown"
        jobs.append(
            {
                "job_id": path.name,
                "title": title,
                "prompt": meta.get("prompt"),
                "created_at": meta.get("created_at"),
                "has_result": has_result,
                "has_final_video": has_final_video,
                "user_id": meta.get("user_id"),
                "status": status,
                "kind": kind,
            }
        )
        if len(jobs) >= limit:
            break
    return jobs


def load_job(job_id: str, *, user_id: Optional[str] = None) -> dict[str, Any]:
    root = artifacts_root() / job_id
    if not root.exists() or not (root / "meta.json").exists():
        if user_id and hydrate_job_from_db(job_id, user_id):
            root = artifacts_root() / job_id
        else:
            raise FileNotFoundError(job_id)

    def _read(name: str) -> Any:
        path = root / name
        if not path.exists():
            return None
        if path.suffix == ".json":
            return json.loads(path.read_text(encoding="utf-8"))
        return path.read_text(encoding="utf-8")

    scenes: list[dict[str, Any]] = []
    scenes_root = root / "scenes"
    if scenes_root.exists():
        for sdir in sorted(scenes_root.iterdir()):
            if not sdir.is_dir():
                continue
            scene: dict[str, Any] = {"scene_id": sdir.name, "files": {}}
            section = sdir / "section.json"
            if section.exists():
                scene["section"] = json.loads(section.read_text(encoding="utf-8"))
            code_final = sdir / "code_final.py"
            if code_final.exists():
                scene["code_final"] = code_final.read_text(encoding="utf-8")

            if (sdir / "scene.mp4").exists():
                scene["video_url"] = (
                    f"/api/jobs/{job_id}/file/scenes/{sdir.name}/scene.mp4"
                )

            reviews = []
            for review_file in sorted(sdir.glob("vlm_r*.json")):
                review = json.loads(review_file.read_text(encoding="utf-8"))
                rev = review.get("revision", 0)
                frame_name = None
                for candidate in sdir.glob(f"vlm_r{rev}_frame.*"):
                    frame_name = candidate.name
                    break
                reviews.append(
                    {
                        **review,
                        "review_file": review_file.name,
                        "frame_url": (
                            f"/api/jobs/{job_id}/file/scenes/{sdir.name}/{frame_name}"
                            if frame_name
                            else None
                        ),
                    }
                )
            scene["vlm_reviews"] = reviews
            comments_file = sdir / "human_comments.json"
            scene["human_comments"] = (
                json.loads(comments_file.read_text(encoding="utf-8"))
                if comments_file.exists()
                else []
            )
            scene["files"] = sorted(p.name for p in sdir.iterdir() if p.is_file())
            scenes.append(scene)

    events: list[dict[str, Any]] = []
    events_path = root / "events.jsonl"
    if events_path.exists():
        for line in events_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                events.append(json.loads(line))

    urls = {
        "scene_plan": f"/api/jobs/{job_id}/file/scene_plan.json",
        "meta": f"/api/jobs/{job_id}/file/meta.json",
        "result": f"/api/jobs/{job_id}/file/result.json",
        "final_debug": f"/api/jobs/{job_id}/file/final_debug.json",
    }
    if (root / "final.mp4").exists():
        urls["final_video"] = f"/api/jobs/{job_id}/file/final.mp4"

    timeline = job_timeline(job_id, scenes)
    marks = list_job_marks(job_id, scenes=scenes, timeline=timeline)
    return {
        "job_id": job_id,
        "meta": _read("meta.json"),
        "scene_plan": _read("scene_plan.json"),
        "final_debug": _read("final_debug.json"),
        "result": _read("result.json"),
        "scenes": scenes,
        "events": events,
        "final_video_url": urls.get("final_video"),
        "urls": urls,
        "timeline": timeline,
        "video_marks": marks,
    }


_MAX_MARK_FRAME_BYTES = 1_500_000


def _decode_mark_frame(frame_base64: str) -> Optional[tuple[bytes, str]]:
    raw = (frame_base64 or "").strip()
    if not raw:
        return None
    ext = ".jpg"
    payload = raw
    if raw.startswith("data:"):
        header, _, payload = raw.partition(",")
        if "png" in header.lower():
            ext = ".png"
        elif "webp" in header.lower():
            ext = ".webp"
    try:
        data = base64.b64decode(payload, validate=False)
    except Exception:
        return None
    if not data or len(data) > _MAX_MARK_FRAME_BYTES:
        return None
    return data, ext


def _save_mark_frame(
    job_id: str, scene_id: str, comment_id: str, frame_base64: Optional[str]
) -> Optional[str]:
    if not frame_base64:
        return None
    decoded = _decode_mark_frame(frame_base64)
    if not decoded:
        return None
    data, ext = decoded
    dest = scene_dir(job_id, scene_id) / "marks" / f"{comment_id}{ext}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return f"/api/jobs/{job_id}/file/scenes/{scene_id}/marks/{dest.name}"


def _mark_frame_path(job_id: str, scene_id: str, comment: dict[str, Any]) -> Optional[Path]:
    frame_url = comment.get("frame_url")
    if not isinstance(frame_url, str) or "/file/" not in frame_url:
        return None
    rel = frame_url.split("/file/", 1)[-1]
    try:
        path = resolve_job_file(job_id, rel)
    except (ValueError, FileNotFoundError):
        return None
    return path if path.is_file() else None


def _scene_summaries_for_timeline(job_id: str) -> list[dict[str, Any]]:
    scenes_root = job_dir(job_id) / "scenes"
    if not scenes_root.exists():
        return []
    out: list[dict[str, Any]] = []
    for sdir in sorted(scenes_root.iterdir()):
        if not sdir.is_dir():
            continue
        section = _read_json_file(sdir / "section.json") or {}
        out.append(
            {
                "scene_id": sdir.name,
                "section": section if isinstance(section, dict) else {},
            }
        )
    return out


def job_timeline(
    job_id: str, scenes: Optional[list[dict[str, Any]]] = None
) -> list[dict[str, Any]]:
    """Map stitched-video time → scene. Uses clip duration when present."""
    if scenes is None:
        scenes = _scene_summaries_for_timeline(job_id)

    path = job_dir(job_id) / "timeline.json"
    newest = 0.0
    for scene in scenes:
        sid = str(scene.get("scene_id") or "")
        if not sid:
            continue
        mp4 = scene_dir(job_id, sid) / "scene.mp4"
        if mp4.exists():
            newest = max(newest, mp4.stat().st_mtime)
    if path.exists() and (newest <= 0 or path.stat().st_mtime >= newest - 0.05):
        cached = _read_json_file(path)
        if isinstance(cached, list) and cached:
            return cached

    from backend.pipeline.compose import probe_duration

    cursor = 0.0
    entries: list[dict[str, Any]] = []
    for scene in scenes:
        sid = str(scene.get("scene_id") or "")
        if not sid:
            continue
        section = scene.get("section") if isinstance(scene.get("section"), dict) else {}
        title = str(section.get("title") or sid)
        planned = float(section.get("duration_seconds") or 8.0)
        mp4 = scene_dir(job_id, sid) / "scene.mp4"
        measured = probe_duration(mp4) if mp4.exists() else 0.0
        duration = measured if measured > 0.2 else planned
        entries.append(
            {
                "scene_id": sid,
                "title": title,
                "start": round(cursor, 3),
                "duration": round(duration, 3),
                "end": round(cursor + duration, 3),
            }
        )
        cursor += duration
    write_json(path, entries)
    return entries


def resolve_timeline_time(
    job_id: str,
    global_timestamp: float,
    *,
    timeline: Optional[list[dict[str, Any]]] = None,
) -> Optional[dict[str, Any]]:
    entries = timeline if timeline is not None else job_timeline(job_id)
    if not entries:
        return None
    t = max(0.0, float(global_timestamp))
    for entry in entries:
        start = float(entry.get("start") or 0.0)
        end = float(entry.get("end") or start)
        if t < end or entry is entries[-1]:
            local = max(0.0, t - start)
            duration = float(entry.get("duration") or 0.0)
            if duration > 0:
                local = min(local, duration)
            return {
                **entry,
                "local_timestamp": round(local, 3),
                "global_timestamp": round(t, 3),
            }
    last = entries[-1]
    return {
        **last,
        "local_timestamp": round(float(last.get("duration") or 0.0), 3),
        "global_timestamp": round(t, 3),
    }


def add_scene_comment(
    job_id: str,
    scene_id: str,
    *,
    comment: str,
    timestamp: Optional[float] = None,
    global_timestamp: Optional[float] = None,
    frame_base64: Optional[str] = None,
    author: str = "Human Reviewer",
) -> dict[str, Any]:
    sdir = scene_dir(job_id, scene_id)
    comments_file = sdir / "human_comments.json"
    comments: list[dict[str, Any]] = []
    if comments_file.exists():
        try:
            comments = json.loads(comments_file.read_text(encoding="utf-8"))
        except Exception:
            comments = []

    comment_id = f"comment_{len(comments) + 1}_{int(datetime.now(timezone.utc).timestamp())}"
    frame_url = _save_mark_frame(job_id, scene_id, comment_id, frame_base64)
    section = _read_json_file(sdir / "section.json") or {}
    comment_entry = {
        "id": comment_id,
        "job_id": job_id,
        "scene_id": scene_id,
        "scene_title": str(section.get("title") or scene_id) if isinstance(section, dict) else scene_id,
        "comment": comment,
        "timestamp": timestamp,
        "global_timestamp": global_timestamp,
        "frame_url": frame_url,
        "author": author,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    comments.append(comment_entry)
    write_json(comments_file, comments)
    return comment_entry


def get_scene_comments(job_id: str, scene_id: str) -> list[dict[str, Any]]:
    sdir = scene_dir(job_id, scene_id)
    comments_file = sdir / "human_comments.json"
    if not comments_file.exists():
        return []
    try:
        loaded = json.loads(comments_file.read_text(encoding="utf-8"))
        return loaded if isinstance(loaded, list) else []
    except Exception:
        return []


def get_scene_comment(
    job_id: str, scene_id: str, comment_id: str
) -> Optional[dict[str, Any]]:
    for item in get_scene_comments(job_id, scene_id):
        if item.get("id") == comment_id:
            return item
    return None


def list_job_marks(
    job_id: str,
    *,
    scenes: Optional[list[dict[str, Any]]] = None,
    timeline: Optional[list[dict[str, Any]]] = None,
) -> list[dict[str, Any]]:
    if scenes is None:
        scenes_root = job_dir(job_id) / "scenes"
        scene_ids = (
            [p.name for p in sorted(scenes_root.iterdir()) if p.is_dir()]
            if scenes_root.exists()
            else []
        )
    else:
        scene_ids = [str(s.get("scene_id") or "") for s in scenes if s.get("scene_id")]
    start_by_id = {
        str(entry.get("scene_id")): float(entry.get("start") or 0.0)
        for entry in (timeline or [])
    }
    marks: list[dict[str, Any]] = []
    for sid in scene_ids:
        if not sid:
            continue
        for item in get_scene_comments(job_id, sid):
            local = item.get("timestamp")
            global_t = item.get("global_timestamp")
            if global_t is None and isinstance(local, (int, float)) and sid in start_by_id:
                global_t = round(start_by_id[sid] + float(local), 3)
            marks.append({**item, "global_timestamp": global_t})
    marks.sort(
        key=lambda m: (
            float(m.get("global_timestamp") if m.get("global_timestamp") is not None else 10**9),
            str(m.get("created_at") or ""),
        )
    )
    return marks


def add_video_mark(
    job_id: str,
    *,
    comment: str,
    author: str = "Human Reviewer",
    scene_id: Optional[str] = None,
    timestamp: Optional[float] = None,
    global_timestamp: Optional[float] = None,
    frame_base64: Optional[str] = None,
) -> dict[str, Any]:
    """Save a learner mark. If scene_id is omitted, resolve it from the stitched timeline."""
    timeline = job_timeline(job_id)
    resolved_scene = scene_id
    local_ts = timestamp
    global_ts = global_timestamp
    hit: Optional[dict[str, Any]] = None
    if not resolved_scene:
        if global_ts is None:
            raise ValueError("Mark the current video time, or pick a scene.")
        hit = resolve_timeline_time(job_id, float(global_ts), timeline=timeline)
        if not hit:
            raise ValueError("No scenes to mark on this video yet.")
        resolved_scene = str(hit["scene_id"])
        local_ts = float(hit["local_timestamp"])
    elif global_ts is None and isinstance(local_ts, (int, float)):
        hit = next((e for e in timeline if e.get("scene_id") == resolved_scene), None)
        if hit:
            global_ts = round(float(hit.get("start") or 0.0) + float(local_ts), 3)
    if local_ts is None and global_ts is not None:
        hit = resolve_timeline_time(job_id, float(global_ts), timeline=timeline)
        if hit and hit.get("scene_id") == resolved_scene:
            local_ts = float(hit["local_timestamp"])

    sdir = scene_dir(job_id, str(resolved_scene))
    if not (sdir / "section.json").exists() and not (sdir / "code_final.py").exists():
        raise FileNotFoundError(f"Scene {resolved_scene} not found")

    entry = add_scene_comment(
        job_id,
        str(resolved_scene),
        comment=comment,
        timestamp=None if local_ts is None else float(local_ts),
        global_timestamp=None if global_ts is None else float(global_ts),
        frame_base64=frame_base64,
        author=author,
    )
    if hit:
        entry["scene_title"] = str(hit.get("title") or entry.get("scene_title") or resolved_scene)
    return entry


def load_comment_frame_bytes(
    job_id: str, scene_id: str, comment_id: Optional[str]
) -> Optional[tuple[bytes, str]]:
    if not comment_id:
        comments = get_scene_comments(job_id, scene_id)
        comment = next((c for c in reversed(comments) if c.get("frame_url")), None)
    else:
        comment = get_scene_comment(job_id, scene_id, comment_id)
    if not comment:
        return None
    path = _mark_frame_path(job_id, scene_id, comment)
    if not path:
        return None
    data = path.read_bytes()
    suffix = path.suffix.lower()
    mime = {".png": "image/png", ".webp": "image/webp"}.get(suffix, "image/jpeg")
    return data, mime


def resolve_job_file(job_id: str, relative: str) -> Path:
    """Resolve a path under the job dir; reject path traversal."""
    root = job_dir(job_id).resolve()
    target = (root / relative).resolve()
    if not str(target).startswith(str(root)):
        raise ValueError("Invalid path")
    if not target.exists() or not target.is_file():
        raise FileNotFoundError(relative)
    return target

"""Persistent job artifacts for debugging (plans, VLM frames, reviews, code)."""

from __future__ import annotations

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
    """Rebuild local job folder from Supabase when /tmp was wiped."""
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


def list_jobs(limit: int = 50, *, user_id: Optional[str] = None) -> list[dict[str, Any]]:
    # Prefer Supabase — local /tmp on Vercel is incomplete across instances.
    if user_id and db.supabase_enabled():
        rows = db.list_user_jobs(user_id, limit=limit)
        if rows:
            return [
                {
                    "job_id": row.get("job_id") or row.get("id"),
                    "title": row.get("title"),
                    "prompt": row.get("prompt"),
                    "created_at": row.get("created_at"),
                    "has_result": bool(row.get("has_result")),
                    "has_final_video": bool(row.get("has_final_video")),
                    "user_id": row.get("user_id") or user_id,
                    "status": row.get("status"),
                }
                for row in rows
                if row.get("job_id") or row.get("id")
            ]

    root = artifacts_root()
    if not root.exists():
        return []
    jobs: list[dict[str, Any]] = []
    for path in sorted(root.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not path.is_dir() or path.name.startswith("."):
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
        title = None
        if plan_path.exists():
            try:
                title = json.loads(plan_path.read_text(encoding="utf-8")).get("title")
            except json.JSONDecodeError:
                pass
        has_result = (path / "result.json").exists()
        has_final_video = (path / "final.mp4").exists()
        if has_result or has_final_video:
            status = "complete"
        elif (path / "scene_plan.json").exists():
            status = "running"
        else:
            status = meta.get("status") or "unknown"
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
    }


def add_scene_comment(
    job_id: str,
    scene_id: str,
    *,
    comment: str,
    timestamp: Optional[float] = None,
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

    comment_entry = {
        "id": f"comment_{len(comments) + 1}_{int(datetime.now(timezone.utc).timestamp())}",
        "job_id": job_id,
        "scene_id": scene_id,
        "comment": comment,
        "timestamp": timestamp,
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
        return json.loads(comments_file.read_text(encoding="utf-8"))
    except Exception:
        return []


def resolve_job_file(job_id: str, relative: str) -> Path:
    """Resolve a path under the job dir; reject path traversal."""
    root = job_dir(job_id).resolve()
    target = (root / relative).resolve()
    if not str(target).startswith(str(root)):
        raise ValueError("Invalid path")
    if not target.exists() or not target.is_file():
        raise FileNotFoundError(relative)
    return target

"""Persistent job artifacts for debugging (plans, VLM frames, reviews, code)."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent
ARTIFACTS_ROOT = ROOT / "artifacts"


def artifacts_root() -> Path:
    ARTIFACTS_ROOT.mkdir(parents=True, exist_ok=True)
    return ARTIFACTS_ROOT


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


def append_event(job_id: str, event: dict[str, Any]) -> None:
    path = job_dir(job_id) / "events.jsonl"
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def init_job(job_id: str, *, prompt: str, settings_snapshot: dict[str, Any]) -> Path:
    root = job_dir(job_id)
    write_json(
        root / "meta.json",
        {
            "job_id": job_id,
            "prompt": prompt,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "settings": settings_snapshot,
        },
    )
    return root


def save_scene_plan(job_id: str, plan: dict[str, Any]) -> str:
    return write_json(job_dir(job_id) / "scene_plan.json", plan)


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


def publish_scene_video(
    job_id: str,
    scene_id: str,
    video_path: Optional[str],
) -> Optional[str]:
    """Copy rendered video into the scene artifact folder for HTTP serving."""
    if not video_path or not Path(video_path).exists():
        return None
    dest = scene_dir(job_id, scene_id) / "scene.mp4"
    shutil.copy2(video_path, dest)
    return f"/api/jobs/{job_id}/file/scenes/{scene_id}/scene.mp4"


def save_result(job_id: str, data: dict[str, Any]) -> str:
    return write_json(job_dir(job_id) / "result.json", data)


def list_jobs(limit: int = 50) -> list[dict[str, Any]]:
    root = artifacts_root()
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
        plan_path = path / "scene_plan.json"
        title = None
        if plan_path.exists():
            try:
                title = json.loads(plan_path.read_text(encoding="utf-8")).get("title")
            except json.JSONDecodeError:
                pass
        jobs.append(
            {
                "job_id": path.name,
                "title": title,
                "prompt": meta.get("prompt"),
                "created_at": meta.get("created_at"),
                "has_result": (path / "result.json").exists(),
            }
        )
        if len(jobs) >= limit:
            break
    return jobs


def load_job(job_id: str) -> dict[str, Any]:
    root = artifacts_root() / job_id
    if not root.exists() or not (root / "meta.json").exists():
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


def resolve_job_file(job_id: str, relative: str) -> Path:
    """Resolve a path under the job dir; reject path traversal."""
    root = job_dir(job_id).resolve()
    target = (root / relative).resolve()
    if not str(target).startswith(str(root)):
        raise ValueError("Invalid path")
    if not target.exists() or not target.is_file():
        raise FileNotFoundError(relative)
    return target

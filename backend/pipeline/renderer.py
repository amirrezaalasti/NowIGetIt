"""Local Manim Community Edition rendering + optional Railway remote worker."""

from __future__ import annotations

import base64
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

import httpx

from backend.code_utils import clean_manim_code, extract_scene_name
from backend.config import get_settings


def render_scene(
    code: str,
    *,
    work_dir: Path,
    resolution: str = "720p",
    scene_id: str = "scene",
) -> tuple[Optional[str], Optional[str], str]:
    """
    Render a Manim Community scene.

    Prefer RENDER_WORKER_URL (Railway) when set; otherwise local Manim when
    ENABLE_MANIM_RENDER=true.

    Returns (video_path, frame_path, log).
    """
    settings = get_settings()
    # Avoid recursion inside the Railway worker container itself.
    worker_mode = os.getenv("RENDER_WORKER_MODE", "").lower() in {"1", "true", "yes"}
    remote_log = ""
    if settings.render_worker_url and not worker_mode:
        video, frame, remote_log = _render_scene_remote(
            code,
            work_dir=work_dir,
            resolution=resolution,
            scene_id=scene_id,
            worker_url=settings.render_worker_url,
            worker_secret=settings.render_worker_secret,
        )
        if video:
            return video, frame, remote_log
        # Wrong/stale worker URL (e.g. HTTP 404) or transient failure → try local.
        remote_log = (
            f"Remote worker failed; falling back to local Manim.\n{remote_log}"
        )

    if not settings.enable_manim_render:
        return (
            None,
            None,
            remote_log
            or "Manim render disabled (set ENABLE_MANIM_RENDER=true or RENDER_WORKER_URL).",
        )

    try:
        import manim  # noqa: F401
    except ImportError:
        return (
            None,
            None,
            (remote_log + "\n" if remote_log else "")
            + "manim (Community Edition) not installed; skipping render.",
        )

    video, frame, local_log = _render_scene_local(
        code,
        work_dir=work_dir,
        resolution=resolution,
        scene_id=scene_id,
    )
    if remote_log:
        local_log = f"{remote_log}\n--- local ---\n{local_log}"
    return video, frame, local_log


def _render_scene_remote(
    code: str,
    *,
    work_dir: Path,
    resolution: str,
    scene_id: str,
    worker_url: str,
    worker_secret: str,
) -> tuple[Optional[str], Optional[str], str]:
    # Ensure Text kerning shim + other normalizations ship with the payload.
    code = clean_manim_code(code)
    headers = {"Content-Type": "application/json"}
    if worker_secret:
        headers["Authorization"] = f"Bearer {worker_secret}"

    try:
        with httpx.Client(timeout=httpx.Timeout(360.0, connect=30.0)) as client:
            res = client.post(
                f"{worker_url}/render",
                headers=headers,
                json={
                    "code": code,
                    "resolution": resolution,
                    "scene_id": scene_id,
                },
            )
    except Exception as exc:  # noqa: BLE001
        return None, None, f"Render worker request failed: {exc}"

    if res.status_code >= 400:
        detail = res.text[:2000]
        return None, None, f"Render worker HTTP {res.status_code}: {detail}"

    try:
        payload = res.json()
    except Exception as exc:  # noqa: BLE001
        return None, None, f"Render worker returned non-JSON: {exc}"

    log = str(payload.get("log") or "")
    if not payload.get("ok"):
        return None, None, str(payload.get("error") or log or "Remote render failed")

    video_b64 = payload.get("video_base64")
    if not video_b64:
        return None, None, f"Remote render missing video.\n{log[-2000:]}"

    out_dir = Path(work_dir).resolve() / scene_id
    out_dir.mkdir(parents=True, exist_ok=True)
    video_path = out_dir / f"{scene_id}.mp4"
    video_path.write_bytes(base64.b64decode(video_b64))

    frame_path: Optional[str] = None
    frame_b64 = payload.get("frame_base64")
    if frame_b64:
        frame_file = out_dir / "preview.png"
        frame_file.write_bytes(base64.b64decode(frame_b64))
        frame_path = str(frame_file)
    else:
        frame_path = _extract_preview_frame(str(video_path), out_dir / "preview.png")

    return str(video_path), frame_path, log[-2500:]


def _render_scene_local(
    code: str,
    *,
    work_dir: Path,
    resolution: str,
    scene_id: str,
) -> tuple[Optional[str], Optional[str], str]:
    code = clean_manim_code(code)
    scene_dir = Path(work_dir).resolve() / scene_id
    scene_dir.mkdir(parents=True, exist_ok=True)
    scene_file = scene_dir / "scene.py"
    scene_file.write_text(code, encoding="utf-8")

    quality_flag = {
        "480p": "-ql",
        "720p": "-qm",
        "1080p": "-qh",
    }.get(resolution, "-qm")

    scene_name = extract_scene_name(code)
    media_dir = (scene_dir / "media").resolve()
    cmd = [
        sys.executable,
        "-m",
        "manim",
        quality_flag,
        "-o",
        f"{scene_id}.mp4",
        "--media_dir",
        str(media_dir),
        str(scene_file),
        scene_name,
    ]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
            cwd=str(scene_dir),
        )
        log = (proc.stdout or "") + "\n" + (proc.stderr or "")
        if proc.returncode != 0:
            return None, None, f"Render failed ({proc.returncode}):\n{log[-5000:]}"
    except Exception as exc:  # noqa: BLE001
        return None, None, f"Render exception: {exc}"

    videos = [
        v
        for v in scene_dir.rglob("*.mp4")
        if "partial_movie_files" not in str(v)
    ]
    if not videos:
        return None, None, f"No mp4 produced.\n{log[-2500:]}"

    video_path = str(sorted(videos, key=lambda p: p.stat().st_mtime)[-1])
    frame_path = _extract_preview_frame(video_path, scene_dir / "preview.png")
    return video_path, frame_path, log[-2500:]


def _extract_preview_frame(video_path: str, frame_path: Path) -> Optional[str]:
    """Grab a frame from the last ~0.25s so VLM sees the finished scene."""
    if not shutil.which("ffmpeg"):
        return None
    frame_path = Path(frame_path)
    attempts = [
        [
            "ffmpeg",
            "-y",
            "-sseof",
            "-0.25",
            "-i",
            video_path,
            "-frames:v",
            "1",
            "-q:v",
            "2",
            str(frame_path),
        ],
        [
            "ffmpeg",
            "-y",
            "-sseof",
            "-1",
            "-i",
            video_path,
            "-frames:v",
            "1",
            "-q:v",
            "2",
            str(frame_path),
        ],
        [
            "ffmpeg",
            "-y",
            "-i",
            video_path,
            "-update",
            "1",
            "-q:v",
            "2",
            str(frame_path),
        ],
    ]
    for cmd in attempts:
        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=30)
            if proc.returncode == 0 and frame_path.exists() and frame_path.stat().st_size > 0:
                return str(frame_path)
        except Exception:  # noqa: BLE001
            continue
    return None


def make_job_dir(job_id: str) -> Path:
    root = Path(tempfile.gettempdir()) / "nowigetit" / job_id
    root.mkdir(parents=True, exist_ok=True)
    return root

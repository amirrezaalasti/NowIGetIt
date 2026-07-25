"""Local Manim Community Edition rendering + end-frame extraction."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

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
    Render a Manim Community scene when ENABLE_MANIM_RENDER=true.

    Returns (video_path, frame_path, log).
    Preview frame is taken from near the END of the clip (final hold),
    not the first second — that was causing empty/title-only VLM frames.
    """
    settings = get_settings()
    if not settings.enable_manim_render:
        return (
            None,
            None,
            "Manim render disabled (ENABLE_MANIM_RENDER=false).",
        )

    try:
        import manim  # noqa: F401
    except ImportError:
        return None, None, "manim (Community Edition) not installed; skipping render."

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
    # Prefer end-of-file seek (final hold / last beat).
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

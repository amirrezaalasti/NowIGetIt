"""Cinematic movie renderer: generated stills + Ken Burns, optional I2V."""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

from backend.config import get_settings
from backend.llm import OpenRouterClient
from backend.pipeline.beat_timing import beat_timeline
from backend.pipeline.movie_shots import MovieBeatShot, MovieShotSpec
from backend.pipeline.renderer import _extract_preview_frame
from backend.schemas import SceneSection

logger = logging.getLogger(__name__)

RESOLUTION_SIZE: dict[str, tuple[int, int]] = {
    "480p": (854, 480),
    "720p": (1280, 720),
    "1080p": (1920, 1080),
}
FPS = 30


def render_movie_scene(
    *,
    client: OpenRouterClient,
    scene: SceneSection,
    spec: MovieShotSpec,
    work_dir: Path,
    resolution: str = "720p",
    previous_frame: Optional[Path] = None,
) -> tuple[Optional[str], Optional[str], str]:
    """Render one movie scene. Returns (video_path, frame_path, log)."""
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    size = RESOLUTION_SIZE.get(resolution, RESOLUTION_SIZE["720p"])
    logs: list[str] = []
    timings = beat_timeline(scene, float(scene.duration_seconds))
    durations = [t.duration for t in timings] if timings else []
    if not durations:
        durations = [max(2.0, float(scene.duration_seconds) or 8.0)]
    shots = list(spec.beats) or [
        MovieBeatShot(image_prompt=scene.visual_description or scene.title)
    ]
    if len(shots) < len(durations):
        shots.extend([shots[-1].model_copy() for _ in range(len(durations) - len(shots))])
    clips: list[Path] = []
    last_png: Optional[Path] = None
    ref_bytes: Optional[bytes] = None
    if previous_frame and Path(previous_frame).exists():
        ref_bytes = Path(previous_frame).read_bytes()

    settings = get_settings()
    want_i2v = bool(settings.enable_movie_video_gen and settings.openrouter_video_model)

    for index, (shot, seconds) in enumerate(zip(shots, durations)):
        seconds = max(1.2, float(seconds))
        still = work_dir / f"beat_{index:02d}.png"
        try:
            png = client.generate_image(
                _full_prompt(spec, shot),
                aspect_ratio="16:9",
                reference_png=ref_bytes,
            )
            still.write_bytes(png)
            _fit_cover(still, size)
            if shot.overlay_text.strip():
                _draw_overlay(still, shot.overlay_text.strip(), size)
            last_png = still
            ref_bytes = still.read_bytes()
            logs.append(f"beat {index}: still ok ({still.stat().st_size} bytes)")
        except Exception as exc:  # noqa: BLE001
            logs.append(f"beat {index}: image failed: {exc}")
            if last_png is None:
                _placeholder_still(still, scene.title, size)
                last_png = still
            else:
                shutil.copy2(last_png, still)

        clip = work_dir / f"beat_{index:02d}.mp4"
        moved = False
        if want_i2v:
            try:
                moved = _image_to_video(
                    client,
                    still=still,
                    shot=shot,
                    seconds=seconds,
                    resolution=resolution,
                    dest=clip,
                )
                if moved:
                    logs.append(f"beat {index}: image-to-video ok")
            except Exception as exc:  # noqa: BLE001
                logs.append(f"beat {index}: image-to-video failed: {exc}")
        if not moved:
            ken, ken_log = ken_burns_clip(
                still, clip, duration=seconds, motion=shot.motion, size=size
            )
            logs.append(f"beat {index}: {ken_log}")
            if not ken:
                continue
        clips.append(clip)

    if not clips:
        frame = last_png or (work_dir / "preview.png")
        if not frame.exists() and last_png:
            shutil.copy2(last_png, frame)
        return None, str(frame) if frame.exists() else None, "\n".join(logs)

    video = work_dir / "scene.mp4"
    concat_ok, concat_log = concat_clips(clips, video)
    logs.append(concat_log)
    if not concat_ok:
        frame = last_png
        return None, str(frame) if frame and frame.exists() else None, "\n".join(logs)

    preview = work_dir / "preview.png"
    frame_path = _extract_preview_frame(str(video), preview)
    if not frame_path and last_png and last_png.exists():
        shutil.copy2(last_png, preview)
        frame_path = str(preview)
    return str(video), frame_path, "\n".join(logs)


def ken_burns_clip(
    image_path: Path,
    output_path: Path,
    *,
    duration: float,
    motion: str = "push_in",
    size: tuple[int, int] = (1280, 720),
) -> tuple[Optional[str], str]:
    """Animate a still with ffmpeg zoompan. Returns (path or None, log)."""
    if not shutil.which("ffmpeg"):
        return None, "ffmpeg not on PATH"
    image_path = Path(image_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    width, height = size
    duration = max(1.0, float(duration))
    frames = max(int(round(duration * FPS)), 2)
    z_expr, x_expr, y_expr = _zoompan_exprs(motion, frames)
    filt = (
        f"scale={width * 3 // 2}:{height * 3 // 2}:force_original_aspect_ratio=increase,"
        f"crop={width * 3 // 2}:{height * 3 // 2},"
        f"zoompan=z='{z_expr}':x='{x_expr}':y='{y_expr}':d={frames}:s={width}x{height}:fps={FPS}"
    )
    cmd = [
        "ffmpeg",
        "-y",
        "-loop",
        "1",
        "-i",
        str(image_path),
        "-vf",
        filt,
        "-t",
        f"{duration:.3f}",
        "-r",
        str(FPS),
        "-pix_fmt",
        "yuv420p",
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        str(output_path),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
    except Exception as exc:  # noqa: BLE001
        return None, f"zoompan exception: {exc}"
    if proc.returncode != 0 or not output_path.exists() or output_path.stat().st_size <= 0:
        hold, hold_log = _hold_clip(image_path, output_path, duration=duration, size=size)
        err = (proc.stderr or "")[-400:]
        if hold:
            return hold, f"zoompan failed, used hold. {err}\n{hold_log}"
        return None, f"zoompan failed: {err}"
    return str(output_path), f"zoompan {motion} {duration:.1f}s"


def concat_clips(clips: list[Path], output_path: Path) -> tuple[bool, str]:
    if not clips:
        return False, "no clips"
    if len(clips) == 1:
        shutil.copy2(clips[0], output_path)
        return True, "single clip"
    if not shutil.which("ffmpeg"):
        return False, "ffmpeg not on PATH"
    list_path = output_path.with_suffix(".concat.txt")
    list_path.write_text(
        "".join(f"file '{c.resolve()}'\n" for c in clips), encoding="utf-8"
    )
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(list_path),
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-an",
        "-preset",
        "veryfast",
        str(output_path),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except Exception as exc:  # noqa: BLE001
        return False, f"concat exception: {exc}"
    if proc.returncode != 0 or not output_path.exists():
        return False, f"concat failed: {(proc.stderr or '')[-400:]}"
    return True, f"concat {len(clips)} clips"


def _image_to_video(
    client: OpenRouterClient,
    *,
    still: Path,
    shot: MovieBeatShot,
    seconds: float,
    resolution: str,
    dest: Path,
) -> bool:
    duration = min(8, max(4, int(round(seconds))))
    blob = client.generate_video_clip(
        shot.camera or shot.image_prompt,
        duration=duration,
        resolution=resolution if resolution in {"720p", "1080p"} else "720p",
        first_frame_png=still.read_bytes(),
    )
    dest.write_bytes(blob)
    if dest.stat().st_size < 1000:
        dest.unlink(missing_ok=True)
        return False
    if abs(duration - seconds) > 0.4:
        _trim_or_pad(dest, seconds)
    return dest.exists() and dest.stat().st_size > 0


def _trim_or_pad(path: Path, seconds: float) -> None:
    if not shutil.which("ffmpeg"):
        return
    tmp = path.with_suffix(".trim.mp4")
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(path),
        "-t",
        f"{seconds:.3f}",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-an",
        "-preset",
        "veryfast",
        str(tmp),
    ]
    proc = subprocess.run(cmd, capture_output=True, timeout=60)
    if proc.returncode == 0 and tmp.exists() and tmp.stat().st_size > 0:
        tmp.replace(path)
    else:
        tmp.unlink(missing_ok=True)


def _hold_clip(
    image_path: Path,
    output_path: Path,
    *,
    duration: float,
    size: tuple[int, int],
) -> tuple[Optional[str], str]:
    width, height = size
    cmd = [
        "ffmpeg",
        "-y",
        "-loop",
        "1",
        "-i",
        str(image_path),
        "-vf",
        f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}",
        "-t",
        f"{duration:.3f}",
        "-r",
        str(FPS),
        "-pix_fmt",
        "yuv420p",
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        str(output_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if proc.returncode != 0 or not output_path.exists():
        return None, (proc.stderr or "")[-300:]
    return str(output_path), "hold still"


def _zoompan_exprs(motion: str, frames: int) -> tuple[str, str, str]:
    n = max(frames - 1, 1)
    center_x = "iw/2-(iw/zoom/2)"
    center_y = "ih/2-(ih/zoom/2)"
    if motion == "pull_out":
        return f"max(1.14-0.14*on/{n},1)", center_x, center_y
    if motion == "pan_left":
        return "1.08", f"(iw-iw/zoom)*on/{n}", center_y
    if motion == "pan_right":
        return "1.08", f"(iw-iw/zoom)*(1-on/{n})", center_y
    if motion == "hold":
        return "1.02", center_x, center_y
    if motion == "drift":
        return f"min(1+0.05*on/{n},1.05)", f"(iw-iw/zoom)*0.2*on/{n}", center_y
    return f"min(1+0.12*on/{n},1.12)", center_x, center_y


def _full_prompt(spec: MovieShotSpec, shot: MovieBeatShot) -> str:
    style = (spec.style or "").strip()
    negative = (spec.negative_prompt or "").strip()
    parts = [shot.image_prompt.strip()]
    if style and style.lower() not in shot.image_prompt.lower():
        parts.append(style)
    parts.append("cinematic educational illustration, 16:9, no captions, no subtitles")
    if negative:
        parts.append(f"Avoid: {negative}")
    return ". ".join(p.rstrip(".") for p in parts if p)


def _fit_cover(path: Path, size: tuple[int, int]) -> None:
    width, height = size
    src_w, src_h = width * 3 // 2, height * 3 // 2
    img = Image.open(path).convert("RGB")
    scale = max(src_w / img.width, src_h / img.height)
    new_size = (max(1, int(img.width * scale)), max(1, int(img.height * scale)))
    img = img.resize(new_size, Image.Resampling.LANCZOS)
    left = max(0, (img.width - src_w) // 2)
    top = max(0, (img.height - src_h) // 2)
    img = img.crop((left, top, left + src_w, top + src_h))
    img.save(path, format="PNG")


def _draw_overlay(path: Path, text: str, size: tuple[int, int]) -> None:
    del size
    img = Image.open(path).convert("RGB")
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype(
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf", 42
        )
    except OSError:
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 42)
        except OSError:
            font = ImageFont.load_default()
    label = text[:48]
    bbox = draw.textbbox((0, 0), label, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (img.width - tw) // 2
    y = img.height - th - 48
    pad = 16
    draw.rectangle(
        (x - pad, y - pad // 2, x + tw + pad, y + th + pad // 2),
        fill=(12, 16, 20),
    )
    draw.text((x, y), label, fill=(242, 242, 236), font=font)
    img.save(path, format="PNG")


def _placeholder_still(path: Path, title: str, size: tuple[int, int]) -> None:
    width, height = size
    img = Image.new("RGB", (width, height), color=(14, 18, 24))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype(
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf", 36
        )
    except OSError:
        font = ImageFont.load_default()
    draw.text((48, height // 2 - 20), (title or "Scene")[:60], fill=(232, 240, 236), font=font)
    img.save(path, format="PNG")

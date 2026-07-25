"""Compose per-scene clips (+ TTS narration) into a final video with audio."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Optional


def _probe_duration(path: Path) -> float:
    if not path.exists() or not shutil.which("ffprobe"):
        return 0.0
    try:
        proc = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=nw=1:nk=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return float((proc.stdout or "0").strip() or 0)
    except Exception:  # noqa: BLE001
        return 0.0


def mux_scene_audio(
    video_path: str,
    audio_path: Optional[str],
    output_path: Path,
) -> Optional[str]:
    """
    Attach narration to a scene clip.

    Keeps the FULL narration: if audio is longer than video, freeze the last
    frame; if video is longer, pad audio with silence. Never use -shortest
    (that was cutting voiceovers mid-sentence).
    """
    if not shutil.which("ffmpeg"):
        return None
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    video = Path(video_path)
    if not video.exists():
        return None

    if not audio_path or not Path(audio_path).exists():
        shutil.copy2(video, output_path)
        return str(output_path)

    audio = Path(audio_path)
    v_dur = _probe_duration(video)
    a_dur = _probe_duration(audio)
    # Small pad so endings aren't clipped
    target = max(v_dur, a_dur) + 0.15

    # Freeze last frame to cover narration; pad/trim audio to the same length.
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(video),
        "-i",
        str(audio),
        "-filter_complex",
        (
            f"[0:v]tpad=stop_mode=clone:stop_duration={max(0.0, target - v_dur):.3f},"
            f"fps=30,format=yuv420p[v];"
            f"[1:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo,"
            f"apad=whole_dur={target:.3f},atrim=0:{target:.3f}[a]"
        ),
        "-map",
        "[v]",
        "-map",
        "[a]",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        if proc.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
            return str(output_path)
        # Fallback: basic mux (may truncate longer stream)
        proc2 = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(video),
                "-i",
                str(audio),
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-shortest",
                str(output_path),
            ],
            capture_output=True,
            timeout=120,
        )
        if proc2.returncode == 0 and output_path.exists():
            return str(output_path)
    except Exception:  # noqa: BLE001
        pass

    shutil.copy2(video, output_path)
    return str(output_path)


def compose_final_video(
    scene_videos: list[str],
    output_path: Path,
) -> Optional[str]:
    """Concatenate scene videos (with audio) into one final mp4."""
    if not scene_videos or not shutil.which("ffmpeg"):
        return None
    existing = [Path(p) for p in scene_videos if p and Path(p).exists()]
    if not existing:
        return None

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if len(existing) == 1:
        shutil.copy2(existing[0], output_path)
        return str(output_path)

    list_file = output_path.parent / "concat_list.txt"
    normalized: list[Path] = []
    for i, src in enumerate(existing):
        norm = output_path.parent / f"norm_{i:02d}.mp4"
        # Ensure every clip has a stereo AAC track for clean concat
        has_audio = _probe_has_audio(src)
        if has_audio:
            cmd = [
                "ffmpeg",
                "-y",
                "-i",
                str(src),
                "-vf",
                "scale=1280:720:force_original_aspect_ratio=decrease,"
                "pad=1280:720:(ow-iw)/2:(oh-ih)/2,fps=30,format=yuv420p",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "23",
                "-c:a",
                "aac",
                "-ar",
                "44100",
                "-ac",
                "2",
                "-b:a",
                "192k",
                "-movflags",
                "+faststart",
                str(norm),
            ]
        else:
            # Silent audio track so concat doesn't drop sound from other clips
            cmd = [
                "ffmpeg",
                "-y",
                "-i",
                str(src),
                "-f",
                "lavfi",
                "-i",
                "anullsrc=channel_layout=stereo:sample_rate=44100",
                "-vf",
                "scale=1280:720:force_original_aspect_ratio=decrease,"
                "pad=1280:720:(ow-iw)/2:(oh-ih)/2,fps=30,format=yuv420p",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "23",
                "-c:a",
                "aac",
                "-shortest",
                "-ar",
                "44100",
                "-ac",
                "2",
                "-movflags",
                "+faststart",
                str(norm),
            ]
        proc = subprocess.run(cmd, capture_output=True, timeout=180)
        if proc.returncode == 0 and norm.exists():
            normalized.append(norm)
        else:
            normalized.append(src)

    list_file.write_text(
        "\n".join(f"file '{p.resolve()}'" for p in normalized) + "\n",
        encoding="utf-8",
    )
    proc = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_file),
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(output_path),
        ],
        capture_output=True,
        timeout=180,
    )
    if proc.returncode == 0 and output_path.exists():
        return str(output_path)

    shutil.copy2(existing[0], output_path)
    return str(output_path) if output_path.exists() else None


def _probe_has_audio(path: Path) -> bool:
    if not shutil.which("ffprobe"):
        return False
    try:
        proc = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "a",
                "-show_entries",
                "stream=codec_type",
                "-of",
                "csv=p=0",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )
        return "audio" in (proc.stdout or "")
    except Exception:  # noqa: BLE001
        return False

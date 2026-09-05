"""Compose per-scene clips (+ TTS narration) into a final video with audio."""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from typing import Optional


logger = logging.getLogger(__name__)


def probe_duration(path: Path) -> float:
    """Return media duration in seconds, or 0 if unknown."""
    path = Path(path)
    if not path.exists():
        return 0.0
    # WAV works without ffprobe (Vercel / Gemini TTS path).
    if path.suffix.lower() == ".wav":
        try:
            from backend.pipeline.tts import wav_duration_seconds

            dur = wav_duration_seconds(path)
            if dur > 0:
                return dur
        except Exception:  # noqa: BLE001
            pass
    if not shutil.which("ffprobe"):
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


def _same_file(a: Path, b: Path) -> bool:
    try:
        return a.resolve() == b.resolve()
    except OSError:
        return str(a) == str(b)


def _srt_timestamp(seconds: float) -> str:
    ms = int(round(max(0.0, seconds) * 1000))
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _chunk_narration(text: str, duration: float) -> list[tuple[float, float, str]]:
    """Split narration into timed subtitle cues spanning `duration` seconds."""
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    if not cleaned or duration <= 0.05:
        return []

    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", cleaned) if p.strip()]
    if not parts:
        parts = [cleaned]

    chunks: list[str] = []
    for part in parts:
        words = part.split()
        if len(words) <= 12:
            chunks.append(part)
            continue
        for i in range(0, len(words), 10):
            piece = " ".join(words[i : i + 10]).strip()
            if piece:
                chunks.append(piece)
    if not chunks:
        return []

    weights = [max(1, len(c)) for c in chunks]
    total_w = float(sum(weights))
    cues: list[tuple[float, float, str]] = []
    t = 0.0
    for i, (chunk, weight) in enumerate(zip(chunks, weights)):
        if i == len(chunks) - 1:
            end = duration
        else:
            end = min(duration, t + max(0.85, duration * (weight / total_w)))
        if end <= t:
            end = min(duration, t + 0.85)
        if t >= duration - 0.05:
            break
        cues.append((t, end, chunk))
        t = end
    if cues:
        start, _end, body = cues[-1]
        cues[-1] = (start, duration, body)
    return cues


def write_narration_srt(
    text: str,
    duration: float,
    output_path: Path,
) -> Optional[Path]:
    """Write an SRT file for narration. Returns path or None if empty."""
    cues = _chunk_narration(text, duration)
    if not cues:
        return None
    lines: list[str] = []
    for i, (start, end, body) in enumerate(cues, start=1):
        lines.append(str(i))
        lines.append(f"{_srt_timestamp(start)} --> {_srt_timestamp(end)}")
        lines.append(body)
        lines.append("")
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path


def concat_audio_files(input_paths: list[Path], output_path: Path) -> Path:
    """Concatenate multiple audio files into one."""
    if not input_paths:
        raise ValueError("No input paths provided")
    
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    concat_list = output_path.parent / f"{output_path.stem}_concat.txt"
    lines = [f"file '{p.resolve()}'" for p in input_paths]
    concat_list.write_text("\n".join(lines), encoding="utf-8")
    
    cmd = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", str(concat_list),
        "-c", "copy",
        str(output_path)
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    concat_list.unlink(missing_ok=True)
    return output_path


def _ffmpeg_subtitles_filter(srt_path: Path) -> str:
    """Build a subtitles= filter fragment with escaped path + readable style."""
    path = str(srt_path.resolve())
    # filtergraph escapes: \ : '
    path = path.replace("\\", "\\\\").replace(":", "\\:").replace("'", r"\'")
    style = (
        "FontName=Arial,FontSize=18,PrimaryColour=&H00FFFFFF&,"
        "OutlineColour=&HAA000000&,BorderStyle=3,Outline=2,Shadow=0,"
        "MarginV=42,Alignment=2"
    )
    return f"subtitles='{path}':force_style='{style}'"


def mux_scene_audio(
    video_path: str,
    audio_path: Optional[str],
    output_path: Path,
    *,
    subtitle_text: Optional[str] = None,
    burn_subtitles: bool = True,
) -> Optional[str]:
    """
    Attach narration to a scene clip and optionally burn-in subtitles.

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

    audio = Path(audio_path) if audio_path and Path(audio_path).exists() else None
    v_dur = probe_duration(video)
    a_dur = probe_duration(audio) if audio else 0.0
    target = max(v_dur, a_dur, 0.5) + (0.15 if audio else 0.0)

    srt_path: Optional[Path] = None
    subs_filter = ""
    if burn_subtitles and (subtitle_text or "").strip():
        srt_path = write_narration_srt(
            subtitle_text or "",
            max(target - 0.15, v_dur, a_dur, 1.0),
            output_path.with_suffix(".srt"),
        )
        if srt_path is not None:
            subs_filter = "," + _ffmpeg_subtitles_filter(srt_path)

    # Avoid ffmpeg/copy writing onto the same inode (re-mux / continue paths).
    write_path = output_path
    if _same_file(video, output_path):
        write_path = output_path.with_name(output_path.stem + ".mux.tmp.mp4")

    def _finalize() -> Optional[str]:
        if write_path == output_path:
            return str(output_path) if output_path.exists() else None
        if not write_path.exists() or write_path.stat().st_size <= 0:
            write_path.unlink(missing_ok=True)
            return None
        write_path.replace(output_path)
        return str(output_path)

    def _run(cmd: list[str]) -> bool:
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
            return proc.returncode == 0 and write_path.exists() and write_path.stat().st_size > 0
        except Exception:  # noqa: BLE001
            return False

    try:
        if audio is not None:
            # Freeze last frame to cover narration; pad/trim audio to same length.
            video_chain = (
                f"[0:v]tpad=stop_mode=clone:stop_duration={max(0.0, target - v_dur):.3f},"
                f"fps=30,format=yuv420p{subs_filter}[v]"
            )
            audio_chain = (
                "[1:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo,"
                f"apad=whole_dur={target:.3f},atrim=0:{target:.3f}[a]"
            )
            cmd = [
                "ffmpeg",
                "-y",
                "-i",
                str(video),
                "-i",
                str(audio),
                "-filter_complex",
                f"{video_chain};{audio_chain}",
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
                str(write_path),
            ]
            if _run(cmd):
                done = _finalize()
                if done:
                    return done
            # Retry without subtitles if libass/subtitles filter failed.
            if subs_filter:
                cmd_no_subs = [
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
                    str(write_path),
                ]
                if _run(cmd_no_subs):
                    done = _finalize()
                    if done:
                        return done
            # Fallback: basic mux (may truncate longer stream)
            if _run(
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
                    str(write_path),
                ]
            ):
                done = _finalize()
                if done:
                    return done
        else:
            # No audio — still burn subtitles when requested.
            vf = f"fps=30,format=yuv420p{subs_filter}"
            if _run(
                [
                    "ffmpeg",
                    "-y",
                    "-i",
                    str(video),
                    "-vf",
                    vf,
                    "-c:v",
                    "libx264",
                    "-preset",
                    "veryfast",
                    "-crf",
                    "23",
                    "-an",
                    "-movflags",
                    "+faststart",
                    str(write_path),
                ]
            ):
                done = _finalize()
                if done:
                    return done
            if subs_filter and _run(
                [
                    "ffmpeg",
                    "-y",
                    "-i",
                    str(video),
                    "-c",
                    "copy",
                    str(write_path),
                ]
            ):
                done = _finalize()
                if done:
                    return done
    finally:
        if write_path != output_path:
            write_path.unlink(missing_ok=True)

    if _same_file(video, output_path):
        return str(output_path)
    shutil.copy2(video, output_path)
    return str(output_path)


def _crossfade_overlap(durations: list[float], *, max_overlap: float = 0.5) -> float:
    """Pick one overlap duration that's safe for every clip pair in the chain."""
    if len(durations) < 2:
        return 0.0
    shortest = min(durations)
    # Never eat more than ~35% of the shortest clip, and never go below a hair
    # (too small a crossfade reads as a glitch rather than a transition).
    overlap = min(max_overlap, shortest * 0.35)
    return overlap if overlap >= 0.12 else 0.0


def _build_crossfade_filter(
    durations: list[float], overlap: float
) -> tuple[str, str, str]:
    """Chain xfade (video) + acrossfade (audio) across N clips.

    Returns (filter_complex, video_out_label, audio_out_label).
    """
    n = len(durations)
    v_label, a_label = "0:v", "0:a"
    running = durations[0]
    parts: list[str] = []
    for i in range(1, n):
        ov = min(overlap, max(0.05, running - 0.05), max(0.05, durations[i] - 0.05))
        offset = max(0.0, running - ov)
        v_out, a_out = f"v{i}", f"a{i}"
        parts.append(
            f"[{v_label}][{i}:v]xfade=transition=fade:duration={ov:.3f}:"
            f"offset={offset:.3f}[{v_out}]"
        )
        parts.append(f"[{a_label}][{i}:a]acrossfade=d={ov:.3f}:c1=tri:c2=tri[{a_out}]")
        v_label, a_label = v_out, a_out
        running = running + durations[i] - ov
    return ";".join(parts), f"[{v_label}]", f"[{a_label}]"


def _compose_with_crossfade(
    clips: list[Path], output_path: Path
) -> Optional[str]:
    """Smoothly blend consecutive scenes instead of hard-cutting between them."""
    if len(clips) < 2 or not shutil.which("ffmpeg"):
        return None
    durations = [probe_duration(p) for p in clips]
    if any(d <= 0 for d in durations):
        return None
    overlap = _crossfade_overlap(durations)
    if overlap <= 0:
        return None

    filter_complex, v_out, a_out = _build_crossfade_filter(durations, overlap)
    cmd = ["ffmpeg", "-y"]
    for clip in clips:
        cmd += ["-i", str(clip)]
    cmd += [
        "-filter_complex",
        filter_complex,
        "-map",
        v_out,
        "-map",
        a_out,
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
        proc = subprocess.run(cmd, capture_output=True, timeout=300)
    except Exception:  # noqa: BLE001
        return None
    if proc.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
        return str(output_path)
    output_path.unlink(missing_ok=True)
    return None


def compose_final_video(
    scene_videos: list[str],
    output_path: Path,
) -> Optional[str]:
    """Stitch scene videos (with audio) into one final mp4.

    Prefers short audio+video crossfades between consecutive scenes so the
    video reads as one continuous piece instead of a slideshow of hard cuts;
    falls back to a plain concat (hard cut) if crossfading isn't possible.
    """
    if not scene_videos or not shutil.which("ffmpeg"):
        return None
    existing = [Path(p) for p in scene_videos if p and Path(p).exists()]
    if not existing:
        return None

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if len(existing) == 1:
        if _same_file(existing[0], output_path):
            return str(output_path)
        _publish_atomically(existing[0], output_path)
        return str(output_path)

    # Scratch files live in a run-private folder: a scene edit re-composing the
    # final video must not stomp on a concurrent compose's normalized clips,
    # and the served final.mp4 is only swapped in once it is complete.
    scratch = Path(tempfile.mkdtemp(prefix="compose_", dir=output_path.parent))
    staged = scratch / "final.mp4"
    try:
        composed = _compose_into(existing, staged, scratch)
        if not composed:
            return None
        _publish_atomically(staged, output_path)
        return str(output_path) if output_path.exists() else None
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def _publish_atomically(src: Path, dest: Path) -> None:
    """Swap `src` into place at `dest` so readers never see a partial file."""
    tmp = dest.with_name(f"{dest.stem}.{uuid.uuid4().hex[:8]}.part{dest.suffix}")
    try:
        shutil.copy2(src, tmp)
        os.replace(tmp, dest)
    finally:
        tmp.unlink(missing_ok=True)


def _compose_into(
    existing: list[Path],
    output_path: Path,
    scratch: Path,
) -> Optional[str]:
    list_file = scratch / "concat_list.txt"
    normalized: list[Path] = []
    for i, src in enumerate(existing):
        norm = scratch / f"norm_{i:02d}.mp4"
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

    crossfaded = _compose_with_crossfade(normalized, output_path)
    if crossfaded:
        return crossfaded

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


def export_looping_gif(
    video_path: Path,
    output_path: Path,
    *,
    width: int = 480,
    fps: int = 12,
) -> Optional[str]:
    """Turn a short mp4 into a looping GIF suitable for sharing."""
    video_path = Path(video_path)
    output_path = Path(output_path)
    if not video_path.exists() or not shutil.which("ffmpeg"):
        return None
    output_path.parent.mkdir(parents=True, exist_ok=True)
    vf = (
        f"fps={fps},scale={width}:-1:flags=lanczos,"
        "split[s0][s1];[s0]palettegen=max_colors=128:stats_mode=full[p];"
        "[s1][p]paletteuse=dither=bayer:bayer_scale=5"
    )
    try:
        proc = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(video_path),
                "-vf",
                vf,
                "-loop",
                "0",
                str(output_path),
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        logger.warning("gif export failed: %s", exc)
        return None
    if proc.returncode != 0 or not output_path.exists() or output_path.stat().st_size < 100:
        err = (proc.stderr or "")[-400:]
        logger.warning("gif export failed: %s", err)
        output_path.unlink(missing_ok=True)
        return None
    return str(output_path)

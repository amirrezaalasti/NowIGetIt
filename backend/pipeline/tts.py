"""Text-to-speech for each scene narration section."""

from __future__ import annotations

import re
import wave
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

import httpx

from backend.config import Settings, get_settings
from backend.tts_voices import normalize_tts_voice

_PCM_RATE_RE = re.compile(r"rate=(\d+)", re.IGNORECASE)
_PCM_CHANNELS_RE = re.compile(r"channels=(\d+)", re.IGNORECASE)


def _is_gemini_tts(model: str) -> bool:
    """Gemini TTS via OpenRouter only accepts response_format=pcm."""
    m = (model or "").lower()
    return "gemini" in m and "tts" in m


def _parse_pcm_params(content_type: Optional[str]) -> tuple[int, int]:
    """Parse sample rate / channels from audio/pcm;rate=24000;channels=1."""
    rate, channels = 24000, 1
    if not content_type:
        return rate, channels
    m_rate = _PCM_RATE_RE.search(content_type)
    m_ch = _PCM_CHANNELS_RE.search(content_type)
    if m_rate:
        rate = int(m_rate.group(1))
    if m_ch:
        channels = int(m_ch.group(1))
    return rate, channels


def pcm_to_wav(
    pcm_bytes: bytes,
    wav_path: Path,
    *,
    sample_rate: int = 24000,
    channels: int = 1,
    sample_width: int = 2,
) -> None:
    """Wrap raw s16le PCM in a WAV container (stdlib — works on Vercel)."""
    wav_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(wav_path), "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_bytes)


def wav_duration_seconds(wav_path: Path) -> float:
    """Duration from WAV header; 0 if unreadable."""
    try:
        with wave.open(str(wav_path), "rb") as wf:
            rate = wf.getframerate()
            if rate <= 0:
                return 0.0
            return wf.getnframes() / float(rate)
    except Exception:  # noqa: BLE001
        return 0.0


def concat_wav_files(
    parts: list[Path],
    output_path: Path,
    *,
    gap_seconds: float = 0.0,
) -> list[float]:
    """Join WAVs into one file, returning each part's duration in order.

    Uses the stdlib rather than ffmpeg so this works on Vercel, where the API
    runs without an ffmpeg binary. `gap_seconds` inserts silence between parts
    and is counted into the preceding part's duration, so the returned numbers
    still tile the output exactly.
    """
    readable = [p for p in parts if Path(p).exists()]
    if not readable:
        return []

    with wave.open(str(readable[0]), "rb") as first:
        params = first.getparams()
    gap_frames = max(0, int(params.framerate * max(0.0, gap_seconds)))
    silence = b"\x00" * (gap_frames * params.sampwidth * params.nchannels)

    durations: list[float] = []
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output_path), "wb") as out:
        out.setnchannels(params.nchannels)
        out.setsampwidth(params.sampwidth)
        out.setframerate(params.framerate)
        for i, part in enumerate(readable):
            with wave.open(str(part), "rb") as wf:
                if (
                    wf.getnchannels() != params.nchannels
                    or wf.getsampwidth() != params.sampwidth
                    or wf.getframerate() != params.framerate
                ):
                    # Mismatched format would play as noise — bail out and let
                    # the caller fall back to a single whole-scene render.
                    return []
                frames = wf.readframes(wf.getnframes())
                count = wf.getnframes()
            out.writeframes(frames)
            trailing = i < len(readable) - 1
            if trailing and gap_frames:
                out.writeframes(silence)
                count += gap_frames
            durations.append(count / float(params.framerate))
    return durations


def _speech_url(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/audio/speech"


def synthesize_narration(
    text: str,
    output_path: Path,
    *,
    settings: Optional[Settings] = None,
    voice: Optional[str] = None,
) -> tuple[Optional[str], bool]:
    """
    Generate speech audio for narration.

    Returns (audio_path or None, skipped).
    Uses OpenRouter's OpenAI-compatible /audio/speech endpoint (default: Gemini TTS).

    Gemini TTS only supports PCM. We wrap that as WAV with the stdlib (no ffmpeg),
    so this works on Vercel. Non-Gemini models that return MP3 keep the .mp3 path.
    """
    settings = settings or get_settings()
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if not settings.tts_api_key or not text.strip():
        return None, True

    resolved_voice = normalize_tts_voice(
        voice, fallback=settings.tts_voice or "Kore"
    )
    use_pcm = _is_gemini_tts(settings.tts_model)
    response_format = "pcm" if use_pcm else "mp3"

    if not use_pcm:
        is_openai = "gpt" in settings.tts_model.lower() or "tts-1" in settings.tts_model.lower() or "openai" in settings.tts_model.lower()
        if is_openai and resolved_voice not in {"alloy", "echo", "fable", "onyx", "nova", "shimmer", "coral", "verse", "ballad", "ash", "sage", "marin", "cedar"}:
            resolved_voice = "alloy"

    headers = {
        "Authorization": f"Bearer {settings.tts_api_key}",
        "Content-Type": "application/json",
    }
    if "openrouter.ai" in settings.tts_base_url:
        headers["HTTP-Referer"] = settings.openrouter_site_url
        headers["X-Title"] = settings.openrouter_app_name

    payload = {
        "model": settings.tts_model,
        "input": text.strip(),
        "voice": resolved_voice,
        "response_format": response_format,
    }

    with httpx.Client(timeout=httpx.Timeout(120.0, connect=30.0)) as client:
        response = client.post(
            _speech_url(settings.tts_base_url),
            headers=headers,
            json=payload,
        )

    if response.status_code != 200:
        detail = response.text[:800]
        raise RuntimeError(
            f"TTS failed ({response.status_code}) model={settings.tts_model!r} "
            f"voice={resolved_voice!r} format={response_format!r}: {detail}"
        )

    if not use_pcm:
        # Keep caller extension when the API already returns a container format.
        out = output_path if output_path.suffix.lower() == ".mp3" else output_path.with_suffix(".mp3")
        out.write_bytes(response.content)
        return str(out), False

    sample_rate, channels = _parse_pcm_params(response.headers.get("content-type"))
    out = output_path.with_suffix(".wav")
    pcm_to_wav(
        response.content,
        out,
        sample_rate=sample_rate,
        channels=channels,
    )
    return str(out), False


# Silence between beats: lets one idea land before the next starts, and gives
# the animation a beat of slack at each hand-off.
BEAT_GAP_SECONDS = 0.18
# Beat lines are short; render them concurrently so per-beat TTS is no slower
# in wall-clock terms than the single whole-scene call it replaces.
_BEAT_TTS_WORKERS = 4


def synthesize_scene_narration(
    beats: list[str],
    output_path: Path,
    *,
    settings: Optional[Settings] = None,
    voice: Optional[str] = None,
) -> tuple[Optional[str], bool, list[float]]:
    """Narrate a scene, measuring how long each beat's own line actually takes.

    Returns (audio_path, skipped, per_beat_durations). Rendering each beat
    separately is what lets the animation be timed to the voiceover exactly
    instead of to an estimate of it: the durations come back measured, and the
    concatenated audio lines up with them frame for frame.

    Falls back to one whole-scene render (with an empty duration list) whenever
    per-beat audio is not available — a single beat, an MP3-only voice, or any
    beat that fails to synthesize.
    """
    settings = settings or get_settings()
    output_path = Path(output_path)
    spoken = [(i, t.strip()) for i, t in enumerate(beats) if t and t.strip()]
    joined = " ".join(t for _, t in spoken)

    def _whole_scene() -> tuple[Optional[str], bool, list[float]]:
        path, skipped = synthesize_narration(
            joined, output_path, settings=settings, voice=voice
        )
        return path, skipped, []

    # Concatenation is stdlib-WAV only, so anything returning MP3 takes the
    # single-call path.
    if len(spoken) < 2 or not _is_gemini_tts(settings.tts_model):
        return _whole_scene()
    if not settings.tts_api_key or not joined:
        return _whole_scene()

    parts_dir = output_path.parent / f"{output_path.stem}_beats"
    parts_dir.mkdir(parents=True, exist_ok=True)

    def _render(item: tuple[int, str]) -> tuple[int, Optional[str]]:
        index, text = item
        try:
            path, _skipped = synthesize_narration(
                text,
                parts_dir / f"beat_{index:02d}.wav",
                settings=settings,
                voice=voice,
            )
        except Exception:  # noqa: BLE001
            return index, None
        return index, path

    with ThreadPoolExecutor(max_workers=_BEAT_TTS_WORKERS) as pool:
        rendered = dict(pool.map(_render, spoken))

    if any(rendered.get(i) is None for i, _ in spoken):
        return _whole_scene()

    ordered = [Path(rendered[i]) for i, _ in spoken]
    measured = concat_wav_files(
        ordered, output_path.with_suffix(".wav"), gap_seconds=BEAT_GAP_SECONDS
    )
    if not measured:
        return _whole_scene()

    # Map durations back onto the original beat positions; silent beats get 0
    # and are treated as pure staging by the timeline.
    per_beat = [0.0] * len(beats)
    for (index, _text), seconds in zip(spoken, measured):
        per_beat[index] = seconds
    return str(output_path.with_suffix(".wav")), False, per_beat

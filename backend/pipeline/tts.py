"""Text-to-speech for each scene narration section."""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
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


def _ffmpeg_exe() -> Optional[str]:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def _parse_pcm_params(content_type: str | None) -> tuple[int, int]:
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


def _pcm_to_mp3(
    pcm_path: Path,
    mp3_path: Path,
    *,
    sample_rate: int = 24000,
    channels: int = 1,
) -> None:
    ffmpeg = _ffmpeg_exe()
    if not ffmpeg:
        raise RuntimeError(
            "ffmpeg is required to convert Gemini TTS PCM audio to MP3"
        )
    result = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-f",
            "s16le",
            "-ar",
            str(sample_rate),
            "-ac",
            str(channels),
            "-i",
            str(pcm_path),
            str(mp3_path),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg PCM→MP3 failed: {result.stderr[-500:] or result.stdout[-500:]}"
        )


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
    Gemini TTS only supports PCM; we convert that to MP3 for the pipeline.

    Uses httpx (not the OpenAI SDK) so Gemini voice names like "Kore" are not
    rejected by OpenAI's voice enum validation.
    """
    settings = settings or get_settings()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if not settings.tts_api_key or not text.strip():
        return None, True

    resolved_voice = normalize_tts_voice(
        voice, fallback=settings.tts_voice or "Kore"
    )
    use_pcm = _is_gemini_tts(settings.tts_model)
    response_format = "pcm" if use_pcm else "mp3"

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
        output_path.write_bytes(response.content)
        return str(output_path), False

    sample_rate, channels = _parse_pcm_params(response.headers.get("content-type"))
    with tempfile.TemporaryDirectory(prefix="nigit-tts-") as tmp:
        pcm_path = Path(tmp) / "speech.pcm"
        pcm_path.write_bytes(response.content)
        _pcm_to_mp3(
            pcm_path,
            output_path,
            sample_rate=sample_rate,
            channels=channels,
        )

    return str(output_path), False

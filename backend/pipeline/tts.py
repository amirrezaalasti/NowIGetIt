"""Text-to-speech for each scene narration section."""

from __future__ import annotations

import re
import wave
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

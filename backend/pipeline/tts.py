"""Text-to-speech for each scene narration section."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from openai import OpenAI

from backend.config import Settings, get_settings
from backend.tts_voices import normalize_tts_voice


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
    Uses an OpenAI-compatible TTS endpoint (default: OpenRouter Gemini TTS).
    """
    settings = settings or get_settings()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if not settings.tts_api_key or not text.strip():
        return None, True

    resolved_voice = normalize_tts_voice(
        voice, fallback=settings.tts_voice or "Kore"
    )

    client_kwargs: dict = {
        "api_key": settings.tts_api_key,
        "base_url": settings.tts_base_url,
    }
    if "openrouter.ai" in settings.tts_base_url:
        client_kwargs["default_headers"] = {
            "HTTP-Referer": settings.openrouter_site_url,
            "X-Title": settings.openrouter_app_name,
        }

    client = OpenAI(**client_kwargs)
    # OpenAI-compatible TTS APIs return binary audio via streaming response.
    with client.audio.speech.with_streaming_response.create(
        model=settings.tts_model,
        voice=resolved_voice,
        input=text.strip(),
        response_format="mp3",
    ) as response:
        response.stream_to_file(output_path)

    return str(output_path), False

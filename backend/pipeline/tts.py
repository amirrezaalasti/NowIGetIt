"""Text-to-speech for each scene narration section."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from openai import OpenAI

from backend.config import Settings, get_settings


def synthesize_narration(
    text: str,
    output_path: Path,
    *,
    settings: Optional[Settings] = None,
) -> tuple[Optional[str], bool]:
    """
    Generate speech audio for narration.

    Returns (audio_path or None, skipped).
    Uses an OpenAI-compatible TTS endpoint when TTS_API_KEY is set.
    OpenRouter does not provide TTS, so this is a separate provider.
    """
    settings = settings or get_settings()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if not settings.tts_api_key or not text.strip():
        return None, True

    client = OpenAI(
        api_key=settings.tts_api_key,
        base_url=settings.tts_base_url,
    )
    # Newer OpenAI TTS APIs return binary audio via streaming response.
    with client.audio.speech.with_streaming_response.create(
        model=settings.tts_model,
        voice=settings.tts_voice,
        input=text.strip(),
        response_format="mp3",
    ) as response:
        response.stream_to_file(output_path)

    return str(output_path), False

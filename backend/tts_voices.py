"""Narrator voices for Gemini TTS via OpenRouter."""

from __future__ import annotations

from typing import Optional, TypedDict

from backend.config import get_settings


class TtsVoice(TypedDict):
    id: str
    gender: str
    label: str


# Canonical Gemini 2.5 flash speech voices supported on OpenRouter / Gemini API.
TTS_VOICES: tuple[TtsVoice, ...] = (
    {"id": "Kore", "gender": "Female", "label": "Kore (Default)"},
    {"id": "Puck", "gender": "Male", "label": "Puck"},
    {"id": "Charon", "gender": "Male", "label": "Charon"},
    {"id": "Fenrir", "gender": "Male", "label": "Fenrir"},
    {"id": "Aoede", "gender": "Female", "label": "Aoede"},
    {"id": "Leda", "gender": "Female", "label": "Leda"},
    {"id": "Callisto", "gender": "Female", "label": "Callisto"},
    {"id": "Europa", "gender": "Female", "label": "Europa"},
    {"id": "Ganymede", "gender": "Male", "label": "Ganymede"},
    {"id": "Titan", "gender": "Male", "label": "Titan"},
    {"id": "Enceladus", "gender": "Male", "label": "Enceladus"},
    {"id": "Hyperion", "gender": "Male", "label": "Hyperion"},
    {"id": "Iapetus", "gender": "Male", "label": "Iapetus"},
    {"id": "Rhea", "gender": "Female", "label": "Rhea"},
    {"id": "Tethys", "gender": "Female", "label": "Tethys"},
    {"id": "Dione", "gender": "Female", "label": "Dione"},
    {"id": "Mimas", "gender": "Male", "label": "Mimas"},
    {"id": "Oberon", "gender": "Male", "label": "Oberon"},
    {"id": "Titania", "gender": "Female", "label": "Titania"},
    {"id": "Ariel", "gender": "Female", "label": "Ariel"},
    {"id": "Umbriel", "gender": "Male", "label": "Umbriel"},
    {"id": "Miranda", "gender": "Female", "label": "Miranda"},
    {"id": "Triton", "gender": "Male", "label": "Triton"},
    {"id": "Nereid", "gender": "Female", "label": "Nereid"},
    {"id": "Proteus", "gender": "Male", "label": "Proteus"},
    {"id": "Phobos", "gender": "Male", "label": "Phobos"},
    {"id": "Deimos", "gender": "Male", "label": "Deimos"},
    {"id": "Io", "gender": "Female", "label": "Io"},
    {"id": "Metis", "gender": "Female", "label": "Metis"},
    {"id": "Adrastea", "gender": "Female", "label": "Adrastea"},
    {"id": "Amalthea", "gender": "Female", "label": "Amalthea"},
    {"id": "Thebe", "gender": "Female", "label": "Thebe"},
    {"id": "Elara", "gender": "Female", "label": "Elara"},
    {"id": "Himalia", "gender": "Female", "label": "Himalia"},
    {"id": "Carme", "gender": "Female", "label": "Carme"},
    {"id": "Ananke", "gender": "Female", "label": "Ananke"},
    {"id": "Pasiphae", "gender": "Female", "label": "Pasiphae"},
    {"id": "Sinope", "gender": "Female", "label": "Sinope"},
    {"id": "Lysithea", "gender": "Female", "label": "Lysithea"},
    {"id": "Kallichore", "gender": "Female", "label": "Kallichore"},
    {"id": "Zubenelgenubi", "gender": "Male", "label": "Zubenelgenubi"},
    # OpenAI Voices
    {"id": "alloy", "gender": "Neutral", "label": "Alloy (OpenAI)"},
    {"id": "echo", "gender": "Male", "label": "Echo (OpenAI)"},
    {"id": "fable", "gender": "Neutral", "label": "Fable (OpenAI)"},
    {"id": "onyx", "gender": "Male", "label": "Onyx (OpenAI)"},
    {"id": "nova", "gender": "Female", "label": "Nova (OpenAI)"},
    {"id": "shimmer", "gender": "Female", "label": "Shimmer (OpenAI)"},
    {"id": "coral", "gender": "Female", "label": "Coral (OpenAI)"},
    {"id": "verse", "gender": "Male", "label": "Verse (OpenAI)"},
    {"id": "ballad", "gender": "Male", "label": "Ballad (OpenAI)"},
    {"id": "ash", "gender": "Male", "label": "Ash (OpenAI)"},
    {"id": "sage", "gender": "Female", "label": "Sage (OpenAI)"},
    {"id": "marin", "gender": "Female", "label": "Marin (OpenAI)"},
    {"id": "cedar", "gender": "Male", "label": "Cedar (OpenAI)"},
)

TTS_VOICE_IDS: frozenset[str] = frozenset(v["id"] for v in TTS_VOICES)
DEFAULT_TTS_VOICE = "Kore"

# Case-insensitive lookup → canonical OpenRouter id
_VOICE_LOOKUP = {v["id"].lower(): v["id"] for v in TTS_VOICES}


def normalize_tts_voice(voice: Optional[str], *, fallback: str = DEFAULT_TTS_VOICE) -> str:
    """Return a canonical Gemini TTS voice id, or fallback if unknown."""
    if voice:
        canonical = _VOICE_LOOKUP.get(voice.strip().lower())
        if canonical:
            return canonical
    fb = _VOICE_LOOKUP.get((fallback or "").strip().lower())
    return fb or DEFAULT_TTS_VOICE


def voices_for_api() -> list[dict[str, str]]:
    settings = get_settings()
    model = settings.tts_model.lower()
    is_openai = "gpt" in model or "tts-1" in model or "openai" in model
    
    openai_ids = {"alloy", "echo", "fable", "onyx", "nova", "shimmer", "coral", "verse", "ballad", "ash", "sage", "marin", "cedar"}
    
    if is_openai:
        filtered = [v for v in TTS_VOICES if v["id"].lower() in openai_ids]
    else:
        filtered = [v for v in TTS_VOICES if v["id"].lower() not in openai_ids]
        
    return [
        {"id": v["id"], "gender": v["gender"], "label": f"{v['label']} · {v['gender']}"}
        for v in filtered
    ]

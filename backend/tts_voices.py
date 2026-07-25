"""Narrator voices for Gemini TTS via OpenRouter."""

from __future__ import annotations

from typing import TypedDict


class TtsVoice(TypedDict):
    id: str
    gender: str
    label: str


# OpenRouter supported_voices for google/gemini-3.1-flash-tts-preview
TTS_VOICES: tuple[TtsVoice, ...] = (
    {"id": "Achernar", "gender": "Female", "label": "Achernar"},
    {"id": "Achird", "gender": "Male", "label": "Achird"},
    {"id": "Algenib", "gender": "Male", "label": "Algenib"},
    {"id": "Algieba", "gender": "Male", "label": "Algieba"},
    {"id": "Alnilam", "gender": "Male", "label": "Alnilam"},
    {"id": "Aoede", "gender": "Female", "label": "Aoede"},
    {"id": "Autonoe", "gender": "Female", "label": "Autonoe"},
    {"id": "Callirrhoe", "gender": "Female", "label": "Callirrhoe"},
    {"id": "Charon", "gender": "Male", "label": "Charon"},
    {"id": "Despina", "gender": "Female", "label": "Despina"},
    {"id": "Enceladus", "gender": "Male", "label": "Enceladus"},
    {"id": "Erinome", "gender": "Female", "label": "Erinome"},
    {"id": "Fenrir", "gender": "Male", "label": "Fenrir"},
    {"id": "Gacrux", "gender": "Female", "label": "Gacrux"},
    {"id": "Iapetus", "gender": "Male", "label": "Iapetus"},
    {"id": "Kore", "gender": "Female", "label": "Kore"},
    {"id": "Laomedeia", "gender": "Female", "label": "Laomedeia"},
    {"id": "Leda", "gender": "Female", "label": "Leda"},
    {"id": "Orus", "gender": "Male", "label": "Orus"},
    {"id": "Pulcherrima", "gender": "Female", "label": "Pulcherrima"},
    {"id": "Puck", "gender": "Male", "label": "Puck"},
    {"id": "Rasalgethi", "gender": "Male", "label": "Rasalgethi"},
    {"id": "Sadachbia", "gender": "Male", "label": "Sadachbia"},
    {"id": "Sadaltager", "gender": "Male", "label": "Sadaltager"},
    {"id": "Schedar", "gender": "Male", "label": "Schedar"},
    {"id": "Sulafat", "gender": "Female", "label": "Sulafat"},
    {"id": "Umbriel", "gender": "Male", "label": "Umbriel"},
    {"id": "Vindemiatrix", "gender": "Female", "label": "Vindemiatrix"},
    {"id": "Zephyr", "gender": "Female", "label": "Zephyr"},
    {"id": "Zubenelgenubi", "gender": "Male", "label": "Zubenelgenubi"},
)

TTS_VOICE_IDS: frozenset[str] = frozenset(v["id"] for v in TTS_VOICES)
DEFAULT_TTS_VOICE = "Kore"

# Case-insensitive lookup → canonical OpenRouter id
_VOICE_LOOKUP = {v["id"].lower(): v["id"] for v in TTS_VOICES}


def normalize_tts_voice(voice: str | None, *, fallback: str = DEFAULT_TTS_VOICE) -> str:
    """Return a canonical Gemini TTS voice id, or fallback if unknown."""
    if voice:
        canonical = _VOICE_LOOKUP.get(voice.strip().lower())
        if canonical:
            return canonical
    fb = _VOICE_LOOKUP.get((fallback or "").strip().lower())
    return fb or DEFAULT_TTS_VOICE


def voices_for_api() -> list[dict[str, str]]:
    return [
        {"id": v["id"], "gender": v["gender"], "label": f"{v['label']} · {v['gender']}"}
        for v in TTS_VOICES
    ]

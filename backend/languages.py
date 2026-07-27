"""Supported narration / on-screen languages for generated videos."""

from __future__ import annotations

from typing import TypedDict


class LanguageOption(TypedDict):
    id: str
    label: str
    native_label: str


# Keep this list practical: languages the planner + Gemini TTS handle well.
LANGUAGES: tuple[LanguageOption, ...] = (
    {"id": "en", "label": "English", "native_label": "English"},
    {"id": "de", "label": "German", "native_label": "Deutsch"},
    {"id": "es", "label": "Spanish", "native_label": "Español"},
    {"id": "fr", "label": "French", "native_label": "Français"},
    {"id": "it", "label": "Italian", "native_label": "Italiano"},
    {"id": "pt", "label": "Portuguese", "native_label": "Português"},
    {"id": "nl", "label": "Dutch", "native_label": "Nederlands"},
    {"id": "pl", "label": "Polish", "native_label": "Polski"},
    {"id": "tr", "label": "Turkish", "native_label": "Türkçe"},
    {"id": "ru", "label": "Russian", "native_label": "Русский"},
    {"id": "zh", "label": "Chinese (Mandarin)", "native_label": "中文"},
    {"id": "ja", "label": "Japanese", "native_label": "日本語"},
    {"id": "ko", "label": "Korean", "native_label": "한국어"},
    {"id": "ar", "label": "Arabic", "native_label": "العربية"},
    {"id": "hi", "label": "Hindi", "native_label": "हिन्दी"},
    {"id": "fa", "label": "Persian", "native_label": "فارسی"},
)

LANGUAGE_IDS: frozenset[str] = frozenset(lang["id"] for lang in LANGUAGES)
DEFAULT_LANGUAGE = "en"

_LANGUAGE_BY_ID = {lang["id"]: lang for lang in LANGUAGES}


def normalize_language(language: Optional[str], *, fallback: str = DEFAULT_LANGUAGE) -> str:
    """Return a supported language id."""
    if language:
        key = language.strip().lower().replace("_", "-")
        # Accept bare codes and BCP-47 prefixes (e.g. en-US → en).
        if key in LANGUAGE_IDS:
            return key
        prefix = key.split("-", 1)[0]
        if prefix in LANGUAGE_IDS:
            return prefix
    fb = (fallback or DEFAULT_LANGUAGE).strip().lower()
    return fb if fb in LANGUAGE_IDS else DEFAULT_LANGUAGE


def language_display_name(language: Optional[str]) -> str:
    lang = _LANGUAGE_BY_ID.get(normalize_language(language))
    if not lang:
        return "English"
    return f"{lang['label']} ({lang['native_label']})"


def languages_for_api() -> list[dict[str, str]]:
    return [
        {
            "id": lang["id"],
            "label": lang["label"],
            "native_label": lang["native_label"],
        }
        for lang in LANGUAGES
    ]

"""Runtime configuration from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Load repo-root .env for local uvicorn (Next.js loads this itself; Python does not).
_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / ".env")
load_dotenv(_ROOT / ".env.local", override=True)


@dataclass(frozen=True)
class Settings:
    openrouter_api_key: str
    openrouter_model: str
    openrouter_vlm_model: str
    openrouter_base_url: str
    openrouter_site_url: str
    openrouter_app_name: str
    tts_api_key: str
    tts_base_url: str
    tts_model: str
    tts_voice: str
    enable_manim_render: bool
    max_scene_revisions: int


def get_settings() -> Settings:
    # Text LLM (planning / codegen). VLM must be multimodal — do not fall back
    # to OPENROUTER_MODEL when it may be text-only (e.g. DeepSeek).
    vlm = (os.getenv("OPENROUTER_VLM_MODEL") or "").strip()
    if not vlm:
        vlm = "google/gemini-2.5-flash-lite"
    return Settings(
        openrouter_api_key=os.getenv("OPENROUTER_API_KEY", ""),
        openrouter_model=os.getenv("OPENROUTER_MODEL", "google/gemini-3.6-flash"),
        openrouter_vlm_model=vlm,
        openrouter_base_url=os.getenv(
            "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"
        ),
        openrouter_site_url=os.getenv("OPENROUTER_SITE_URL", "https://nowigetit.app"),
        openrouter_app_name=os.getenv("OPENROUTER_APP_NAME", "NowIGetIt"),
        tts_api_key=os.getenv("TTS_API_KEY", ""),
        tts_base_url=os.getenv("TTS_BASE_URL", "https://api.openai.com/v1"),
        tts_model=os.getenv("TTS_MODEL", "gpt-4o-mini-tts"),
        tts_voice=os.getenv("TTS_VOICE", "alloy"),
        enable_manim_render=os.getenv("ENABLE_MANIM_RENDER", "false").lower()
        in {"1", "true", "yes"},
        max_scene_revisions=int(os.getenv("MAX_SCENE_REVISIONS", "2")),
    )

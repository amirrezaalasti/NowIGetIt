"""Runtime configuration from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values, load_dotenv

# Load repo-root .env for local uvicorn (Next.js loads this itself; Python does not).
_ROOT = Path(__file__).resolve().parent.parent


def _load_env_files() -> None:
    """Load .env then .env.local, but never let empty local values wipe .env.

    Override existing process env so stale exports (e.g. from `vercel env pull`)
    cannot silently point TTS at OpenAI while the UI offers Gemini voices.
    """
    load_dotenv(_ROOT / ".env", override=True)
    local_path = _ROOT / ".env.local"
    if not local_path.exists():
        return
    for key, value in dotenv_values(local_path).items():
        if key and value is not None and str(value).strip():
            os.environ[key] = str(value)


_load_env_files()


@dataclass(frozen=True)
class Settings:
    openrouter_api_key: str
    openrouter_model: str
    openrouter_model_manim: str
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
    enable_auto_vlm_revise: bool
    vlm_clarity_threshold: float
    supabase_url: str
    supabase_service_role_key: str
    default_llm_estimate_tokens: int
    render_worker_url: str
    render_worker_secret: str
    docling_worker_url: str
    docling_worker_secret: str


def get_settings() -> Settings:
    # Text LLM (planning / codegen). VLM must be multimodal — do not fall back
    # to OPENROUTER_MODEL when it may be text-only (e.g. DeepSeek).
    vlm = (os.getenv("OPENROUTER_VLM_MODEL") or "").strip()
    if not vlm:
        vlm = "google/gemini-2.5-flash-lite"
    text_model = os.getenv("OPENROUTER_MODEL", "google/gemini-3.6-flash")
    manim_model = (os.getenv("OPENROUTER_MODEL_MANIM") or "").strip() or text_model
    return Settings(
        openrouter_api_key=os.getenv("OPENROUTER_API_KEY", ""),
        openrouter_model=text_model,
        openrouter_model_manim=manim_model,
        openrouter_vlm_model=vlm,
        openrouter_base_url=os.getenv(
            "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"
        ),
        openrouter_site_url=os.getenv("OPENROUTER_SITE_URL", "https://nowigetit.app"),
        openrouter_app_name=os.getenv("OPENROUTER_APP_NAME", "NowIGetIt"),
        # TTS defaults to OpenRouter (Gemini 3.1 Flash TTS Preview). Leave
        # TTS_API_KEY blank to reuse OPENROUTER_API_KEY.
        tts_api_key=(os.getenv("TTS_API_KEY") or "").strip()
        or os.getenv("OPENROUTER_API_KEY", ""),
        tts_base_url=os.getenv(
            "TTS_BASE_URL", "https://openrouter.ai/api/v1"
        ),
        tts_model=os.getenv(
            "TTS_MODEL", "google/gemini-3.1-flash-tts-preview"
        ),
        tts_voice=os.getenv("TTS_VOICE", "Kore"),
        enable_manim_render=os.getenv("ENABLE_MANIM_RENDER", "false").lower()
        in {"1", "true", "yes"},
        max_scene_revisions=int(os.getenv("MAX_SCENE_REVISIONS", "5")),
        enable_auto_vlm_revise=os.getenv("ENABLE_AUTO_VLM_REVISE", "true").lower()
        in {"1", "true", "yes"},
        vlm_clarity_threshold=float(os.getenv("VLM_CLARITY_THRESHOLD", "0.55")),
        supabase_url=(
            os.getenv("SUPABASE_URL")
            or os.getenv("NEXT_PUBLIC_SUPABASE_URL")
            or ""
        ).strip(),
        supabase_service_role_key=os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip(),
        default_llm_estimate_tokens=int(
            os.getenv("DEFAULT_LLM_ESTIMATE_TOKENS", "25000")
        ),
        render_worker_url=(os.getenv("RENDER_WORKER_URL") or "").strip().rstrip("/"),
        render_worker_secret=(os.getenv("RENDER_WORKER_SECRET") or "").strip(),
        docling_worker_url=(os.getenv("DOCLING_WORKER_URL") or "").strip().rstrip("/"),
        docling_worker_secret=(os.getenv("DOCLING_WORKER_SECRET") or "").strip(),
    )

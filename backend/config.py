"""Runtime configuration from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Optional

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


def _clean_model_id(value: str, *, fallback: str = "") -> str:
    """Strip whitespace and accidental leading '~' from OpenRouter model ids."""
    cleaned = (value or "").strip().lstrip("~").strip()
    return cleaned or fallback


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
    _load_env_files()
    # Text LLM (planning / codegen). VLM must be multimodal — do not fall back
    # to OPENROUTER_MODEL when it may be text-only (e.g. DeepSeek).
    vlm = _clean_model_id(os.getenv("OPENROUTER_VLM_MODEL") or "")
    if not vlm or "deepseek" in vlm.lower():
        vlm = "google/gemini-2.5-flash-lite"
    text_model = _clean_model_id(
        os.getenv("OPENROUTER_MODEL") or "",
        fallback="google/gemini-3.6-flash",
    )
    manim_model = _clean_model_id(os.getenv("OPENROUTER_MODEL_MANIM") or "") or text_model
    server_or_key = (os.getenv("OPENROUTER_API_KEY") or "").strip()
    tts_key = (os.getenv("TTS_API_KEY") or "").strip() or server_or_key
    return Settings(
        openrouter_api_key=server_or_key,
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
        tts_api_key=tts_key,
        tts_base_url=os.getenv(
            "TTS_BASE_URL", "https://openrouter.ai/api/v1"
        ),
        tts_model=os.getenv(
            "TTS_MODEL", "google/gemini-3.1-flash-tts-preview"
        ),
        tts_voice=os.getenv("TTS_VOICE", "Kore"),
        enable_manim_render=os.getenv("ENABLE_MANIM_RENDER", "false").lower()
        in {"1", "true", "yes"},
        max_scene_revisions=int(os.getenv("MAX_SCENE_REVISIONS", "3")),
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


def settings_for_user(user_id: Optional[str] = None) -> Settings:
    """Resolve settings for a signed-in user.

    If the user has saved their own OpenRouter key (BYOK), that key is used for
    **all** OpenRouter LLM + TTS calls for this request. The server
    OPENROUTER_API_KEY / TTS_API_KEY are never used as a fallback for that user.
    """
    base = get_settings()
    if not user_id:
        return base

    has_key = False
    user_key: Optional[str] = None
    load_error: Optional[BaseException] = None
    try:
        from backend import supabase_db as db

        has_key = bool(db.user_has_openrouter_key(user_id))
        user_key = db.get_user_openrouter_key(user_id) if has_key else None
    except Exception as exc:  # noqa: BLE001
        load_error = exc
        try:
            from backend import sqlite_db

            has_key = bool(sqlite_db.user_has_openrouter_key(user_id))
            user_key = sqlite_db.get_user_openrouter_key(user_id) if has_key else None
            load_error = None
        except Exception as exc2:  # noqa: BLE001
            load_error = exc2

    if load_error is not None and has_key:
        raise ValueError(
            "Your OpenRouter API key is saved but could not be loaded. "
            "Re-save it from the account menu — the server key will not be used."
        ) from load_error

    if not has_key:
        return base
    if not user_key:
        raise ValueError(
            "Your OpenRouter API key is saved but could not be loaded. "
            "Re-save it from the account menu — the server key will not be used."
        )

    # Force OpenRouter TTS with the user's key so we never spend the server
    # OpenAI/OpenRouter TTS credentials for BYOK users.
    from backend.tts_voices import DEFAULT_TTS_VOICE, normalize_tts_voice

    tts_voice = normalize_tts_voice(base.tts_voice, fallback=DEFAULT_TTS_VOICE)
    openai_voices = {
        "alloy",
        "echo",
        "fable",
        "onyx",
        "nova",
        "shimmer",
        "coral",
        "verse",
        "ballad",
        "ash",
        "sage",
        "marin",
        "cedar",
    }
    if tts_voice.lower() in openai_voices:
        tts_voice = DEFAULT_TTS_VOICE

    return replace(
        base,
        openrouter_api_key=user_key,
        tts_api_key=user_key,
        tts_base_url="https://openrouter.ai/api/v1",
        tts_model=_clean_model_id(
            os.getenv("TTS_MODEL_BYOK") or "",
            fallback="google/gemini-3.1-flash-tts-preview",
        ),
        tts_voice=tts_voice,
    )

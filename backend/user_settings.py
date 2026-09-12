"""Bring-your-own-key (BYOK) providers, encrypted storage, and Settings overlay."""

from __future__ import annotations

import json
import os
import threading
from contextvars import ContextVar
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from backend.config import Settings, _clean_model_id, get_platform_settings, set_settings_override
from backend.crypto_box import decrypt_text, encrypt_text, mask_secret

_LOCK = threading.Lock()
_bound_user: ContextVar[Optional[str]] = ContextVar("byok_user_id", default=None)

ProviderKind = str  # "llm" | "tts" | "both"


PROVIDERS: dict[str, dict[str, Any]] = {
    "openrouter": {
        "id": "openrouter",
        "label": "OpenRouter",
        "kind": "both",
        "base_url": "https://openrouter.ai/api/v1",
        "default_llm": "deepseek/deepseek-v4-flash",
        "default_manim": "google/gemini-3.6-flash",
        "default_vlm": "google/gemini-2.5-flash-lite",
        "default_tts": "google/gemini-3.1-flash-tts-preview",
        "docs_url": "https://openrouter.ai/keys",
        "placeholder": "sk-or-…",
        "notes": "One key covers hundreds of models, including Gemini TTS.",
    },
    "openai": {
        "id": "openai",
        "label": "OpenAI",
        "kind": "both",
        "base_url": "https://api.openai.com/v1",
        "default_llm": "gpt-4.1-mini",
        "default_manim": "gpt-4.1",
        "default_vlm": "gpt-4.1-mini",
        "default_tts": "gpt-4o-mini-tts",
        "docs_url": "https://platform.openai.com/api-keys",
        "placeholder": "sk-…",
        "notes": "Chat, vision, and TTS (alloy / nova / …).",
    },
    "google": {
        "id": "google",
        "label": "Google Gemini",
        "kind": "both",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "default_llm": "gemini-2.5-flash",
        "default_manim": "gemini-2.5-pro",
        "default_vlm": "gemini-2.5-flash",
        "default_tts": "gemini-2.5-flash-preview-tts",
        "docs_url": "https://aistudio.google.com/apikey",
        "placeholder": "AIza…",
        "notes": "OpenAI-compatible Gemini endpoint (LLM, VLM, TTS).",
    },
    "anthropic": {
        "id": "anthropic",
        "label": "Anthropic",
        "kind": "llm",
        "base_url": "https://api.anthropic.com/v1",
        "default_llm": "claude-sonnet-4-5",
        "default_manim": "claude-sonnet-4-5",
        "default_vlm": "claude-sonnet-4-5",
        "default_tts": "",
        "docs_url": "https://console.anthropic.com/settings/keys",
        "placeholder": "sk-ant-…",
        "notes": "OpenAI-compatible Messages API. Pair with another provider for TTS.",
    },
    "groq": {
        "id": "groq",
        "label": "Groq",
        "kind": "llm",
        "base_url": "https://api.groq.com/openai/v1",
        "default_llm": "llama-3.3-70b-versatile",
        "default_manim": "llama-3.3-70b-versatile",
        "default_vlm": "meta-llama/llama-4-scout-17b-16e-instruct",
        "default_tts": "",
        "docs_url": "https://console.groq.com/keys",
        "placeholder": "gsk_…",
        "notes": "Fast open models. Use OpenRouter or OpenAI for TTS.",
    },
    "deepseek": {
        "id": "deepseek",
        "label": "DeepSeek",
        "kind": "llm",
        "base_url": "https://api.deepseek.com",
        "default_llm": "deepseek-chat",
        "default_manim": "deepseek-chat",
        "default_vlm": "",
        "default_tts": "",
        "docs_url": "https://platform.deepseek.com/api_keys",
        "placeholder": "sk-…",
        "notes": "Text models only — pick a VLM provider (OpenRouter / Gemini / OpenAI).",
    },
    "mistral": {
        "id": "mistral",
        "label": "Mistral",
        "kind": "llm",
        "base_url": "https://api.mistral.ai/v1",
        "default_llm": "mistral-small-latest",
        "default_manim": "mistral-medium-latest",
        "default_vlm": "pixtral-12b-2409",
        "default_tts": "",
        "docs_url": "https://console.mistral.ai/api-keys",
        "placeholder": "…",
        "notes": "OpenAI-compatible. Pair with another provider for TTS.",
    },
    "xai": {
        "id": "xai",
        "label": "xAI (Grok)",
        "kind": "llm",
        "base_url": "https://api.x.ai/v1",
        "default_llm": "grok-3-mini",
        "default_manim": "grok-3",
        "default_vlm": "grok-2-vision-1212",
        "default_tts": "",
        "docs_url": "https://console.x.ai",
        "placeholder": "xai-…",
        "notes": "OpenAI-compatible Grok models.",
    },
    "together": {
        "id": "together",
        "label": "Together AI",
        "kind": "llm",
        "base_url": "https://api.together.xyz/v1",
        "default_llm": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
        "default_manim": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
        "default_vlm": "meta-llama/Llama-4-Scout-17B-16E-Instruct",
        "default_tts": "",
        "docs_url": "https://api.together.xyz/settings/api-keys",
        "placeholder": "…",
        "notes": "OpenAI-compatible. Pair with another provider for TTS.",
    },
    "fireworks": {
        "id": "fireworks",
        "label": "Fireworks",
        "kind": "llm",
        "base_url": "https://api.fireworks.ai/inference/v1",
        "default_llm": "accounts/fireworks/models/llama-v3p3-70b-instruct",
        "default_manim": "accounts/fireworks/models/llama-v3p3-70b-instruct",
        "default_vlm": "accounts/fireworks/models/llama4-scout-instruct-basic",
        "default_tts": "",
        "docs_url": "https://fireworks.ai/account/api-keys",
        "placeholder": "fw_…",
        "notes": "OpenAI-compatible. Pair with another provider for TTS.",
    },
    "custom": {
        "id": "custom",
        "label": "Custom (OpenAI-compatible)",
        "kind": "both",
        "base_url": "",
        "default_llm": "",
        "default_manim": "",
        "default_vlm": "",
        "default_tts": "",
        "docs_url": "",
        "placeholder": "sk-…",
        "notes": "Any OpenAI-compatible /v1 host. You set the base URL and model ids.",
    },
}

LLM_PROVIDER_IDS = tuple(PROVIDERS.keys())
_DEFAULT_PREFS = {
    "llm_provider": "openrouter",
    "tts_provider": "openrouter",
    "llm_model": "",
    "manim_model": "",
    "vlm_model": "",
    "tts_model": "",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _store_path(user_id: str) -> Path:
    from backend.artifacts import artifacts_root

    root = artifacts_root() / "_local" / "user_secrets"
    root.mkdir(parents=True, exist_ok=True)
    safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in user_id)
    return root / f"{safe}.json"


def _empty_store() -> dict[str, Any]:
    return {"keys": {}, "prefs": dict(_DEFAULT_PREFS), "youtube": None}


def load_store(user_id: str) -> dict[str, Any]:
    path = _store_path(user_id)
    if not path.exists():
        return _empty_store()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return _empty_store()
    if not isinstance(data, dict):
        return _empty_store()
    keys = data.get("keys") if isinstance(data.get("keys"), dict) else {}
    prefs = {**_DEFAULT_PREFS}
    raw_prefs = data.get("prefs") if isinstance(data.get("prefs"), dict) else {}
    for key in _DEFAULT_PREFS:
        val = raw_prefs.get(key)
        if isinstance(val, str):
            prefs[key] = val.strip()
    youtube = data.get("youtube") if isinstance(data.get("youtube"), dict) else None
    return {"keys": keys, "prefs": prefs, "youtube": youtube}


def _write_store(user_id: str, data: dict[str, Any]) -> None:
    path = _store_path(user_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def providers_for_api() -> list[dict[str, Any]]:
    rows = []
    for item in PROVIDERS.values():
        rows.append(
            {
                "id": item["id"],
                "label": item["label"],
                "kind": item["kind"],
                "base_url": item["base_url"],
                "default_llm": item["default_llm"],
                "default_manim": item["default_manim"],
                "default_vlm": item["default_vlm"],
                "default_tts": item["default_tts"],
                "docs_url": item["docs_url"],
                "placeholder": item["placeholder"],
                "notes": item["notes"],
            }
        )
    return rows


def list_configured_keys(user_id: str) -> list[dict[str, Any]]:
    store = load_store(user_id)
    rows: list[dict[str, Any]] = []
    for provider, rec in store["keys"].items():
        if not isinstance(rec, dict) or not rec.get("ciphertext"):
            continue
        rows.append(
            {
                "provider": provider,
                "configured": True,
                "hint": rec.get("hint") or "••••",
                "base_url": rec.get("base_url") or PROVIDERS.get(provider, {}).get("base_url") or "",
                "updated_at": rec.get("updated_at"),
            }
        )
    return rows


def save_provider_key(
    user_id: str,
    provider: str,
    api_key: str,
    *,
    base_url: Optional[str] = None,
) -> dict[str, Any]:
    provider = (provider or "").strip().lower()
    if provider not in PROVIDERS:
        raise ValueError(f"Unknown provider: {provider}")
    key = (api_key or "").strip()
    if len(key) < 8:
        raise ValueError("API key looks too short")
    if provider == "custom":
        url = (base_url or "").strip().rstrip("/")
        if not url.startswith("http"):
            raise ValueError("Custom provider needs an https base URL")
    else:
        url = (base_url or "").strip().rstrip("/") or None
        if url and not url.startswith("http"):
            raise ValueError("Base URL must start with http")
    with _LOCK:
        store = load_store(user_id)
        store["keys"][provider] = {
            "ciphertext": encrypt_text(key),
            "hint": mask_secret(key),
            "base_url": url,
            "updated_at": _now(),
        }
        _write_store(user_id, store)
    return {
        "provider": provider,
        "configured": True,
        "hint": mask_secret(key),
        "base_url": url or PROVIDERS[provider]["base_url"],
        "updated_at": store["keys"][provider]["updated_at"],
    }


def delete_provider_key(user_id: str, provider: str) -> None:
    provider = (provider or "").strip().lower()
    with _LOCK:
        store = load_store(user_id)
        store["keys"].pop(provider, None)
        _write_store(user_id, store)


def save_prefs(user_id: str, prefs: dict[str, Any]) -> dict[str, str]:
    with _LOCK:
        store = load_store(user_id)
        current = store["prefs"]
        for key in _DEFAULT_PREFS:
            if key not in prefs:
                continue
            val = prefs.get(key)
            if val is None:
                continue
            text = str(val).strip()
            if key in {"llm_provider", "tts_provider"} and text and text not in PROVIDERS:
                raise ValueError(f"Unknown provider: {text}")
            current[key] = text
        store["prefs"] = current
        _write_store(user_id, store)
        return dict(current)


def _decrypt_key(rec: dict[str, Any]) -> Optional[str]:
    token = rec.get("ciphertext")
    if not isinstance(token, str) or not token:
        return None
    try:
        return decrypt_text(token)
    except (ValueError, RuntimeError):
        return None


def get_provider_secret(user_id: str, provider: str) -> Optional[tuple[str, Optional[str]]]:
    """Return (api_key, base_url_override) or None."""
    rec = load_store(user_id)["keys"].get(provider)
    if not isinstance(rec, dict):
        return None
    secret = _decrypt_key(rec)
    if not secret:
        return None
    url = rec.get("base_url")
    url_s = url.strip().rstrip("/") if isinstance(url, str) and url.strip() else None
    return secret, url_s


def _db_openrouter_key(user_id: str) -> Optional[str]:
    """OpenRouter key saved via /api/me/openrouter-key (account menu)."""
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
    if has_key and not user_key:
        raise ValueError(
            "Your OpenRouter API key is saved but could not be loaded. "
            "Re-save it from the account menu — the server key will not be used."
        )
    return user_key


def using_own_llm_key(user_id: Optional[str]) -> bool:
    if not user_id:
        return False
    settings = settings_for_user(user_id)
    platform = get_platform_settings()
    return bool(settings.openrouter_api_key) and (
        settings.openrouter_api_key != platform.openrouter_api_key
        or settings.openrouter_base_url != platform.openrouter_base_url
    )


def _pick_provider(
    store: dict[str, Any],
    preferred: str,
    *,
    need_tts: bool = False,
) -> Optional[str]:
    keys: dict[str, Any] = store["keys"]
    order = [preferred]
    if preferred != "openrouter":
        order.append("openrouter")
    for pid in LLM_PROVIDER_IDS:
        if pid not in order:
            order.append(pid)
    for pid in order:
        rec = keys.get(pid)
        if not isinstance(rec, dict) or not rec.get("ciphertext"):
            continue
        spec = PROVIDERS.get(pid) or {}
        kind = spec.get("kind") or "llm"
        if need_tts and kind == "llm":
            continue
        return pid
    return None


def settings_for_user(user_id: Optional[str]) -> Settings:
    platform = get_platform_settings()
    if not user_id:
        return platform
    store = load_store(user_id)
    prefs = store["prefs"]
    llm_pref = prefs.get("llm_provider") or "openrouter"
    tts_pref = prefs.get("tts_provider") or llm_pref

    llm_id = _pick_provider(store, llm_pref, need_tts=False)
    tts_id = _pick_provider(store, tts_pref, need_tts=True) or llm_id

    if not llm_id:
        db_key = _db_openrouter_key(user_id)
        if db_key:
            from backend.tts_voices import DEFAULT_TTS_VOICE, normalize_tts_voice

            tts_voice = normalize_tts_voice(
                platform.tts_voice, fallback=DEFAULT_TTS_VOICE
            )
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
                platform,
                openrouter_api_key=db_key,
                tts_api_key=db_key,
                tts_base_url="https://openrouter.ai/api/v1",
                tts_model=_clean_model_id(
                    os.getenv("TTS_MODEL_BYOK") or "",
                    fallback="google/gemini-3.1-flash-tts-preview",
                ),
                tts_voice=tts_voice,
            )

    llm_key = platform.openrouter_api_key
    llm_base = platform.openrouter_base_url
    llm_model = platform.openrouter_model
    manim_model = platform.openrouter_model_manim
    vlm_model = platform.openrouter_vlm_model

    if llm_id:
        secret = get_provider_secret(user_id, llm_id)
        spec = PROVIDERS.get(llm_id) or {}
        if secret:
            llm_key, override_base = secret
            llm_base = override_base or spec.get("base_url") or llm_base
            llm_model = prefs.get("llm_model") or spec.get("default_llm") or llm_model
            manim_model = prefs.get("manim_model") or spec.get("default_manim") or manim_model
            vlm_default = spec.get("default_vlm") or ""
            vlm_model = prefs.get("vlm_model") or vlm_default or vlm_model
            if not vlm_default and not prefs.get("vlm_model"):
                # Text-only provider: keep platform VLM (usually OpenRouter Gemini).
                vlm_model = platform.openrouter_vlm_model

    tts_key = platform.tts_api_key
    tts_base = platform.tts_base_url
    tts_model = platform.tts_model

    if tts_id:
        secret = get_provider_secret(user_id, tts_id)
        spec = PROVIDERS.get(tts_id) or {}
        if secret and spec.get("kind") in {"both", "tts"}:
            tts_key, override_base = secret
            tts_base = override_base or spec.get("base_url") or tts_base
            tts_model = prefs.get("tts_model") or spec.get("default_tts") or tts_model
        elif llm_id == tts_id and llm_key:
            spec = PROVIDERS.get(llm_id) or {}
            if spec.get("kind") == "both":
                tts_key = llm_key
                tts_base = llm_base
                tts_model = prefs.get("tts_model") or spec.get("default_tts") or tts_model

    if prefs.get("llm_model"):
        llm_model = prefs["llm_model"]
    if prefs.get("manim_model"):
        manim_model = prefs["manim_model"]
    if prefs.get("vlm_model"):
        vlm_model = prefs["vlm_model"]
    if prefs.get("tts_model"):
        tts_model = prefs["tts_model"]

    return replace(
        platform,
        openrouter_api_key=llm_key,
        openrouter_base_url=llm_base,
        openrouter_model=llm_model,
        openrouter_model_manim=manim_model,
        openrouter_vlm_model=vlm_model,
        tts_api_key=tts_key,
        tts_base_url=tts_base,
        tts_model=tts_model,
    )


def apply_user_settings(user_id: Optional[str]) -> Settings:
    settings = settings_for_user(user_id)
    set_settings_override(settings)
    _bound_user.set(user_id)
    return settings


def apply_settings_for_job(job_id: str) -> Settings:
    from backend import artifacts as store

    owner = store.job_owner_id(job_id)
    return apply_user_settings(owner)


def public_key_state(user_id: str) -> dict[str, Any]:
    platform = get_platform_settings()
    settings = settings_for_user(user_id)
    store = load_store(user_id)
    own_llm = using_own_llm_key(user_id)
    own_tts = bool(settings.tts_api_key) and (
        settings.tts_api_key != platform.tts_api_key
        or settings.tts_base_url != platform.tts_base_url
    )
    return {
        "providers": providers_for_api(),
        "keys": list_configured_keys(user_id),
        "prefs": store["prefs"],
        "platform": {
            "llm": bool(platform.openrouter_api_key),
            "tts": bool(platform.tts_api_key),
        },
        "active": {
            "llm_provider": store["prefs"].get("llm_provider") or "openrouter",
            "tts_provider": store["prefs"].get("tts_provider") or "openrouter",
            "llm_model": settings.openrouter_model,
            "manim_model": settings.openrouter_model_manim,
            "vlm_model": settings.openrouter_vlm_model,
            "tts_model": settings.tts_model,
            "using_own_llm_key": own_llm,
            "using_own_tts_key": own_tts,
            "llm_ready": bool(settings.openrouter_api_key),
            "tts_ready": bool(settings.tts_api_key),
        },
    }


def validate_provider_key(
    user_id: str,
    provider: str,
    api_key: Optional[str] = None,
    *,
    base_url: Optional[str] = None,
) -> dict[str, Any]:
    """Hit GET /models (OpenAI-compatible) to confirm the key works."""
    import httpx

    provider = (provider or "").strip().lower()
    spec = PROVIDERS.get(provider)
    if not spec:
        raise ValueError(f"Unknown provider: {provider}")
    secret = (api_key or "").strip()
    url = (base_url or "").strip().rstrip("/")
    if not secret:
        stored = get_provider_secret(user_id, provider)
        if not stored:
            raise ValueError("No key saved for this provider")
        secret, stored_url = stored
        url = url or stored_url or spec.get("base_url") or ""
    url = url or spec.get("base_url") or ""
    if not url:
        raise ValueError("Base URL is required")
    headers = {
        "Authorization": f"Bearer {secret}",
    }
    if provider == "openrouter":
        headers["HTTP-Referer"] = get_platform_settings().openrouter_site_url
        headers["X-Title"] = get_platform_settings().openrouter_app_name
    if provider == "anthropic":
        headers["x-api-key"] = secret
        headers["anthropic-version"] = "2023-06-01"
    with httpx.Client(timeout=20.0) as client:
        response = client.get(f"{url.rstrip('/')}/models", headers=headers)
    if response.status_code >= 400:
        detail = (response.text or "")[:240]
        raise ValueError(f"Provider rejected the key (HTTP {response.status_code}): {detail}")
    return {"ok": True, "provider": provider}

from __future__ import annotations

from backend.crypto_box import decrypt_text, encrypt_text, mask_secret
from backend.paper_pipeline import DEFAULT_PAPER_PROMPT, compose_paper_prompt
from backend.user_settings import (
    PROVIDERS,
    apply_user_settings,
    save_prefs,
    save_provider_key,
    settings_for_user,
    using_own_llm_key,
)


def test_encrypt_roundtrip(monkeypatch) -> None:
    monkeypatch.setenv("AUTH_SECRET", "test-secret-for-byok-keys")
    token = encrypt_text("sk-or-v1-super-secret")
    assert "super-secret" not in token
    assert decrypt_text(token) == "sk-or-v1-super-secret"
    assert mask_secret("sk-or-v1-abcdef1234").startswith("sk-o")


def test_settings_overlay_uses_user_key(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AUTH_SECRET", "test-secret-for-byok-keys")
    monkeypatch.setenv("ARTIFACTS_ROOT", str(tmp_path))
    monkeypatch.setenv("OPENROUTER_API_KEY", "platform-key-aaaaaaaa")
    monkeypatch.setenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    monkeypatch.setattr("backend.config._load_env_files", lambda: None)
    save_provider_key("u1", "openai", "sk-user-openai-key-123456")
    save_prefs("u1", {"llm_provider": "openai", "tts_provider": "openai"})
    settings = settings_for_user("u1")
    assert settings.openrouter_api_key == "sk-user-openai-key-123456"
    assert "openai.com" in settings.openrouter_base_url
    assert using_own_llm_key("u1") is True
    apply_user_settings("u1")
    from backend.config import get_platform_settings, get_settings, set_settings_override

    assert get_settings().openrouter_api_key == "sk-user-openai-key-123456"
    assert get_platform_settings().openrouter_api_key == "platform-key-aaaaaaaa"
    set_settings_override(None)


def test_unknown_provider_rejected(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AUTH_SECRET", "test-secret-for-byok-keys")
    monkeypatch.setenv("ARTIFACTS_ROOT", str(tmp_path))
    try:
        save_provider_key("u1", "not-a-provider", "sk-12345678")
        assert False, "expected ValueError"
    except ValueError:
        pass
    assert "openrouter" in PROVIDERS


def test_paper_prompt_defaults() -> None:
    assert compose_paper_prompt("") == DEFAULT_PAPER_PROMPT
    text = compose_paper_prompt("Focus on theorem 2")
    assert "theorem 2" in text
    assert "attached paper" in text.lower() or "FROM the attached" in text

"""Encrypt / decrypt per-user secrets (OpenRouter API keys) at rest.

Uses only the Python standard library so local SQLite / Mongo BYOK works
even when PyJWT is not on the interpreter path (uvicorn still uses the venv).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
from typing import Optional


def _secret() -> str:
    secret = (os.getenv("AUTH_SECRET") or "").strip()
    if secret:
        return secret
    # Dev fallback so local BYOK still round-trips; production must set AUTH_SECRET.
    return "nowigetit-dev-secret"


def _key_material() -> bytes:
    return hashlib.sha256(_secret().encode("utf-8")).digest()


def _keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    out = bytearray()
    counter = 0
    while len(out) < length:
        block = hashlib.sha256(key + nonce + counter.to_bytes(4, "big")).digest()
        out.extend(block)
        counter += 1
    return bytes(out[:length])


def encrypt_secret(plain: str) -> str:
    text = (plain or "").strip()
    if not text:
        raise ValueError("API key is empty")
    key = _key_material()
    nonce = secrets.token_bytes(16)
    data = text.encode("utf-8")
    cipher = bytes(a ^ b for a, b in zip(data, _keystream(key, nonce, len(data))))
    mac = hmac.new(key, nonce + cipher, hashlib.sha256).digest()[:16]
    return base64.urlsafe_b64encode(nonce + mac + cipher).decode("ascii")


def decrypt_secret(token: Optional[str]) -> Optional[str]:
    if not token or not str(token).strip():
        return None
    try:
        raw = base64.urlsafe_b64decode(str(token).strip().encode("ascii"))
    except Exception:  # noqa: BLE001
        return None
    if len(raw) < 33:
        return None
    nonce, mac, cipher = raw[:16], raw[16:32], raw[32:]
    key = _key_material()
    expected = hmac.new(key, nonce + cipher, hashlib.sha256).digest()[:16]
    if not hmac.compare_digest(mac, expected):
        return None
    plain = bytes(a ^ b for a, b in zip(cipher, _keystream(key, nonce, len(cipher))))
    try:
        text = plain.decode("utf-8").strip()
    except UnicodeDecodeError:
        return None
    return text or None


def mask_api_key(plain: Optional[str]) -> Optional[str]:
    if not plain:
        return None
    key = plain.strip()
    if len(key) <= 8:
        return "••••••••"
    return f"{key[:7]}…{key[-4:]}"


def key_fingerprint(plain: str) -> str:
    """Stable short fingerprint for UI (not secret)."""
    return hashlib.sha256(plain.strip().encode("utf-8")).hexdigest()[:12]

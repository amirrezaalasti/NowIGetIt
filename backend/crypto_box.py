"""Authenticated encryption for per-user secrets (API keys, YouTube tokens).

Uses SHAKE-256 as a stream cipher plus HMAC-SHA256 (encrypt-then-MAC).
The key is derived from BYOK_ENCRYPTION_KEY or AUTH_SECRET.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets

_PREFIX = b"nig1"
_NONCE_LEN = 16
_MAC_LEN = 32


def _master_key() -> bytes:
    secret = (
        (os.getenv("BYOK_ENCRYPTION_KEY") or "").strip()
        or (os.getenv("AUTH_SECRET") or "").strip()
        or (os.getenv("NEXTAUTH_SECRET") or "").strip()
    )
    if not secret:
        raise RuntimeError(
            "Set BYOK_ENCRYPTION_KEY or AUTH_SECRET to store provider keys."
        )
    return hashlib.sha256(f"nowigetit-byok-v1:{secret}".encode("utf-8")).digest()


def encrypt_text(plaintext: str) -> str:
    key = _master_key()
    nonce = secrets.token_bytes(_NONCE_LEN)
    raw = plaintext.encode("utf-8")
    stream = hashlib.shake_256(key + nonce).digest(len(raw))
    ct = bytes(a ^ b for a, b in zip(raw, stream))
    mac = hmac.new(key, _PREFIX + nonce + ct, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(_PREFIX + nonce + mac + ct).decode("ascii")


def decrypt_text(token: str) -> str:
    key = _master_key()
    try:
        blob = base64.urlsafe_b64decode(token.encode("ascii"))
    except Exception as exc:  # noqa: BLE001
        raise ValueError("Invalid secret token") from exc
    if len(blob) < len(_PREFIX) + _NONCE_LEN + _MAC_LEN:
        raise ValueError("Invalid secret token")
    if blob[: len(_PREFIX)] != _PREFIX:
        raise ValueError("Invalid secret token")
    nonce = blob[len(_PREFIX) : len(_PREFIX) + _NONCE_LEN]
    mac = blob[len(_PREFIX) + _NONCE_LEN : len(_PREFIX) + _NONCE_LEN + _MAC_LEN]
    ct = blob[len(_PREFIX) + _NONCE_LEN + _MAC_LEN :]
    expected = hmac.new(key, _PREFIX + nonce + ct, hashlib.sha256).digest()
    if not hmac.compare_digest(mac, expected):
        raise ValueError("Invalid secret token")
    stream = hashlib.shake_256(key + nonce).digest(len(ct))
    raw = bytes(a ^ b for a, b in zip(ct, stream))
    return raw.decode("utf-8")


def mask_secret(value: str, *, keep_start: int = 4, keep_end: int = 4) -> str:
    text = (value or "").strip()
    if len(text) <= keep_start + keep_end:
        return "••••"
    return f"{text[:keep_start]}…{text[-keep_end:]}"

"""YouTube Data API: OAuth token storage, channel lookup, resumable upload."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlencode

import httpx
import jwt

from backend import artifacts as store
from backend.crypto_box import decrypt_text, encrypt_text
from backend.user_settings import _LOCK, _now, _write_store, load_store

YOUTUBE_UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
YOUTUBE_READONLY_SCOPE = "https://www.googleapis.com/auth/youtube.readonly"
YOUTUBE_SCOPES = f"{YOUTUBE_UPLOAD_SCOPE} {YOUTUBE_READONLY_SCOPE}"
TOKEN_URL = "https://oauth2.googleapis.com/token"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
API = "https://www.googleapis.com/youtube/v3"
UPLOAD_API = "https://www.googleapis.com/upload/youtube/v3/videos"


def youtube_oauth_configured() -> bool:
    return bool(_client_id() and _client_secret())


def _client_id() -> str:
    return (os.getenv("AUTH_GOOGLE_ID") or os.getenv("YOUTUBE_GOOGLE_ID") or "").strip()


def _client_secret() -> str:
    return (
        os.getenv("AUTH_GOOGLE_SECRET") or os.getenv("YOUTUBE_GOOGLE_SECRET") or ""
    ).strip()


def _auth_secret() -> str:
    return (os.getenv("AUTH_SECRET") or os.getenv("NEXTAUTH_SECRET") or "").strip()


def redirect_uri_for(origin: str) -> str:
    return f"{origin.rstrip('/')}/api/youtube/callback"


def public_status(user_id: str) -> dict[str, Any]:
    rec = load_store(user_id).get("youtube")
    connected = isinstance(rec, dict) and bool(rec.get("ciphertext"))
    return {
        "configured": youtube_oauth_configured(),
        "connected": connected,
        "channel_title": rec.get("channel_title") if isinstance(rec, dict) else None,
        "channel_id": rec.get("channel_id") if isinstance(rec, dict) else None,
        "updated_at": rec.get("updated_at") if isinstance(rec, dict) else None,
    }


def auth_url(*, user_id: str, origin: str, return_to: str = "/pipeline") -> str:
    if not youtube_oauth_configured():
        raise RuntimeError(
            "Google OAuth is not configured. Set AUTH_GOOGLE_ID and AUTH_GOOGLE_SECRET."
        )
    secret = _auth_secret()
    if not secret:
        raise RuntimeError("AUTH_SECRET is not configured")
    dest = return_to if return_to.startswith("/") and not return_to.startswith("//") else "/pipeline"
    state = jwt.encode(
        {"sub": user_id, "return_to": dest, "typ": "youtube-oauth"},
        secret,
        algorithm="HS256",
    )
    params = {
        "client_id": _client_id(),
        "redirect_uri": redirect_uri_for(origin),
        "response_type": "code",
        "scope": YOUTUBE_SCOPES,
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
    }
    return f"{AUTH_URL}?{urlencode(params)}"


def decode_oauth_state(state: str) -> dict[str, str]:
    secret = _auth_secret()
    if not secret:
        raise ValueError("AUTH_SECRET is not configured")
    try:
        payload = jwt.decode(state, secret, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise ValueError("Invalid YouTube OAuth state") from exc
    if payload.get("typ") != "youtube-oauth":
        raise ValueError("Invalid YouTube OAuth state")
    user_id = payload.get("sub")
    if not isinstance(user_id, str) or not user_id:
        raise ValueError("Invalid YouTube OAuth state")
    return_to = payload.get("return_to") or "/pipeline"
    if not isinstance(return_to, str) or not return_to.startswith("/") or return_to.startswith("//"):
        return_to = "/pipeline"
    return {"user_id": user_id, "return_to": return_to}


def complete_oauth(*, user_id: str, code: str, origin: str) -> dict[str, Any]:
    if not youtube_oauth_configured():
        raise RuntimeError("Google OAuth is not configured")
    with httpx.Client(timeout=30.0) as client:
        response = client.post(
            TOKEN_URL,
            data={
                "client_id": _client_id(),
                "client_secret": _client_secret(),
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri_for(origin),
            },
        )
    if response.status_code >= 400:
        raise RuntimeError(f"YouTube token exchange failed: {response.text[:400]}")
    tokens = response.json()
    refresh = tokens.get("refresh_token")
    access = tokens.get("access_token")
    if not access:
        raise RuntimeError("YouTube did not return an access token")
    expires_in = int(tokens.get("expires_in") or 3600)
    channel = _fetch_channel(str(access))
    payload = {
        "refresh_token": refresh,
        "access_token": access,
        "expires_at": int(time.time()) + max(expires_in - 60, 60),
        "scope": tokens.get("scope") or YOUTUBE_SCOPES,
        "channel_id": channel.get("id"),
        "channel_title": channel.get("title"),
    }
    _save_youtube(user_id, payload, channel)
    return public_status(user_id)


def disconnect(user_id: str) -> dict[str, Any]:
    with _LOCK:
        data = load_store(user_id)
        data["youtube"] = None
        _write_store(user_id, data)
    return public_status(user_id)


def _save_youtube(user_id: str, payload: dict[str, Any], channel: dict[str, Any]) -> None:
    with _LOCK:
        data = load_store(user_id)
        existing = {}
        rec = data.get("youtube")
        if isinstance(rec, dict) and rec.get("ciphertext"):
            try:
                existing = json.loads(decrypt_text(rec["ciphertext"]))
            except Exception:  # noqa: BLE001
                existing = {}
        if not payload.get("refresh_token") and existing.get("refresh_token"):
            payload["refresh_token"] = existing["refresh_token"]
        data["youtube"] = {
            "ciphertext": encrypt_text(json.dumps(payload)),
            "channel_id": channel.get("id") or payload.get("channel_id"),
            "channel_title": channel.get("title") or payload.get("channel_title"),
            "updated_at": _now(),
        }
        _write_store(user_id, data)


def _load_tokens(user_id: str) -> dict[str, Any]:
    rec = load_store(user_id).get("youtube")
    if not isinstance(rec, dict) or not rec.get("ciphertext"):
        raise RuntimeError("YouTube is not connected. Connect it in Settings or Pipeline.")
    data = json.loads(decrypt_text(str(rec["ciphertext"])))
    if not isinstance(data, dict):
        raise RuntimeError("YouTube credentials are unreadable. Reconnect YouTube.")
    return data


def _access_token(user_id: str) -> str:
    tokens = _load_tokens(user_id)
    access = tokens.get("access_token")
    expires_at = int(tokens.get("expires_at") or 0)
    if access and expires_at > int(time.time()) + 30:
        return str(access)
    refresh = tokens.get("refresh_token")
    if not refresh:
        raise RuntimeError("YouTube refresh token missing. Disconnect and reconnect YouTube.")
    with httpx.Client(timeout=30.0) as client:
        response = client.post(
            TOKEN_URL,
            data={
                "client_id": _client_id(),
                "client_secret": _client_secret(),
                "grant_type": "refresh_token",
                "refresh_token": refresh,
            },
        )
    if response.status_code >= 400:
        raise RuntimeError(f"YouTube token refresh failed: {response.text[:400]}")
    body = response.json()
    access = body.get("access_token")
    if not access:
        raise RuntimeError("YouTube token refresh returned no access token")
    tokens["access_token"] = access
    tokens["expires_at"] = int(time.time()) + max(int(body.get("expires_in") or 3600) - 60, 60)
    if body.get("refresh_token"):
        tokens["refresh_token"] = body["refresh_token"]
    channel = {
        "id": tokens.get("channel_id"),
        "title": tokens.get("channel_title"),
    }
    _save_youtube(user_id, tokens, channel)
    return str(access)


def _fetch_channel(access_token: str) -> dict[str, Any]:
    with httpx.Client(timeout=20.0) as client:
        response = client.get(
            f"{API}/channels",
            params={"part": "snippet", "mine": "true"},
            headers={"Authorization": f"Bearer {access_token}"},
        )
    if response.status_code >= 400:
        return {}
    items = (response.json() or {}).get("items") or []
    if not items:
        return {}
    item = items[0]
    snippet = item.get("snippet") or {}
    return {"id": item.get("id"), "title": snippet.get("title")}


def upload_video(
    *,
    user_id: str,
    video_path: Path,
    title: str,
    description: str = "",
    privacy: str = "unlisted",
    tags: Optional[list[str]] = None,
) -> dict[str, Any]:
    path = Path(video_path)
    if not path.exists():
        raise FileNotFoundError(f"Video file not found: {path}")
    privacy_status = privacy if privacy in {"public", "unlisted", "private"} else "unlisted"
    access = _access_token(user_id)
    size = path.stat().st_size
    metadata = {
        "snippet": {
            "title": (title or "Now I Get It")[:100],
            "description": (description or "")[:4900],
            "tags": [t for t in (tags or ["NowIGetIt", "explainer"]) if t][:10],
            "categoryId": "27",
        },
        "status": {
            "privacyStatus": privacy_status,
            "selfDeclaredMadeForKids": False,
        },
    }
    headers = {
        "Authorization": f"Bearer {access}",
        "Content-Type": "application/json; charset=UTF-8",
        "X-Upload-Content-Length": str(size),
        "X-Upload-Content-Type": "video/mp4",
    }
    with httpx.Client(timeout=httpx.Timeout(120.0, connect=30.0)) as client:
        session = client.post(
            UPLOAD_API,
            params={"uploadType": "resumable", "part": "snippet,status"},
            headers=headers,
            json=metadata,
        )
        if session.status_code >= 400:
            raise RuntimeError(f"YouTube upload session failed: {session.text[:500]}")
        location = session.headers.get("Location")
        if not location:
            raise RuntimeError("YouTube did not return an upload URL")
        with path.open("rb") as handle:
            put = client.put(
                location,
                content=handle,
                headers={
                    "Authorization": f"Bearer {access}",
                    "Content-Type": "video/mp4",
                    "Content-Length": str(size),
                },
                timeout=httpx.Timeout(600.0, connect=30.0),
            )
        if put.status_code >= 400:
            raise RuntimeError(f"YouTube upload failed: {put.text[:500]}")
        body = put.json() if put.content else {}
    video_id = str(body.get("id") or "")
    if not video_id:
        raise RuntimeError("YouTube upload succeeded but returned no video id")
    return {
        "video_id": video_id,
        "url": f"https://www.youtube.com/watch?v={video_id}",
        "title": title,
        "privacy": privacy_status,
        "channel_title": public_status(user_id).get("channel_title"),
    }


def publish_job(
    *,
    user_id: str,
    job_id: str,
    title: Optional[str] = None,
    description: Optional[str] = None,
    privacy: str = "unlisted",
    tags: Optional[list[str]] = None,
) -> dict[str, Any]:
    store.assert_job_owner(job_id, user_id)
    root = store.job_dir(job_id)
    video = root / "final.mp4"
    if not video.exists():
        raise FileNotFoundError("This job has no final.mp4 yet")
    job = store.load_job(job_id, user_id=user_id)
    meta = job.get("meta") if isinstance(job.get("meta"), dict) else {}
    plan = job.get("scene_plan") if isinstance(job.get("scene_plan"), dict) else {}
    resolved_title = (
        (title or "").strip()
        or str(plan.get("title") or meta.get("title") or "Now I Get It")
    )
    summary = str(plan.get("concept_summary") or "").strip()
    resolved_desc = (description or "").strip() or (
        f"{summary}\n\nCreated with Now I Get It — https://nowigetit.app"
        if summary
        else "Created with Now I Get It."
    )
    result = upload_video(
        user_id=user_id,
        video_path=video,
        title=resolved_title,
        description=resolved_desc,
        privacy=privacy,
        tags=tags,
    )
    youtube_meta = {
        **(meta.get("youtube") if isinstance(meta.get("youtube"), dict) else {}),
        **result,
        "published_at": _now(),
    }
    store.patch_job_meta(job_id, youtube=youtube_meta, kind=meta.get("kind") or "video")
    return result

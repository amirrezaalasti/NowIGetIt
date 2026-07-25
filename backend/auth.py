"""JWT auth for FastAPI — tokens issued by the Next.js /api/auth/api-token route."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Annotated, Optional

import jwt
from fastapi import Depends, Header, HTTPException, Query


@dataclass(frozen=True)
class AuthUser:
    id: str
    email: Optional[str] = None
    name: Optional[str] = None
    image: Optional[str] = None


def _auth_secret() -> str:
    return (os.getenv("AUTH_SECRET") or os.getenv("NEXTAUTH_SECRET") or "").strip()


def auth_is_configured() -> bool:
    return bool(_auth_secret())


def _decode_user(token: str) -> AuthUser:
    secret = _auth_secret()
    if not secret:
        raise HTTPException(
            status_code=500,
            detail="AUTH_SECRET is not configured on the API",
        )
    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            audience="nowigetit-api",
            issuer="nowigetit",
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired token") from exc

    user_id = payload.get("sub")
    if not user_id or not isinstance(user_id, str):
        raise HTTPException(status_code=401, detail="Invalid token subject")

    email = payload.get("email")
    name = payload.get("name")
    image = payload.get("image")
    return AuthUser(
        id=user_id,
        email=email if isinstance(email, str) else None,
        name=name if isinstance(name, str) else None,
        image=image if isinstance(image, str) else None,
    )


def get_current_user(
    authorization: Annotated[Optional[str], Header()] = None,
) -> AuthUser:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Authentication required")
    return _decode_user(authorization.split(" ", 1)[1].strip())


def get_current_user_from_header_or_query(
    authorization: Annotated[Optional[str], Header()] = None,
    access_token: Annotated[Optional[str], Query()] = None,
) -> AuthUser:
    """For media URLs (<video>/<img>) that cannot send Authorization headers."""
    if authorization and authorization.lower().startswith("bearer "):
        return _decode_user(authorization.split(" ", 1)[1].strip())
    if access_token:
        return _decode_user(access_token.strip())
    raise HTTPException(status_code=401, detail="Authentication required")


CurrentUser = Annotated[AuthUser, Depends(get_current_user)]
MediaUser = Annotated[AuthUser, Depends(get_current_user_from_header_or_query)]

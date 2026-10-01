"""Session tokens.

AUTH_PROVIDER=local    -> the API issues and verifies HS256 JWTs itself.
AUTH_PROVIDER=supabase -> the API verifies Supabase-issued JWTs against the project's JWKS.
Either way the rest of the app only sees a `TokenClaims`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache

import jwt

from launchpad.config import get_settings

_ISSUER = "launchpad"


class InvalidToken(Exception):
    pass


@dataclass(frozen=True)
class TokenClaims:
    subject: str  # local: user UUID; supabase: auth user id
    email: str | None


def issue_token(user_id: uuid.UUID, email: str) -> str:
    s = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "email": email,
        "iss": _ISSUER,
        "iat": now,
        "exp": now + timedelta(minutes=s.jwt_ttl_minutes),
    }
    return jwt.encode(payload, s.require_jwt_secret(), algorithm="HS256")


@lru_cache
def _supabase_jwks() -> jwt.PyJWKClient:
    s = get_settings()
    if not s.supabase_url:
        raise InvalidToken("SUPABASE_URL is required when AUTH_PROVIDER=supabase")
    return jwt.PyJWKClient(f"{s.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json")


def verify_token(token: str) -> TokenClaims:
    s = get_settings()
    try:
        if s.auth_provider == "supabase":
            key = _supabase_jwks().get_signing_key_from_jwt(token)
            data = jwt.decode(
                token,
                key.key,
                algorithms=["ES256", "RS256"],
                audience=s.supabase_jwt_audience,
            )
        else:
            data = jwt.decode(token, s.require_jwt_secret(), algorithms=["HS256"], issuer=_ISSUER)
    except jwt.PyJWTError as exc:
        raise InvalidToken(str(exc)) from exc
    sub = data.get("sub")
    if not isinstance(sub, str):
        raise InvalidToken("token has no subject")
    email = data.get("email")
    return TokenClaims(subject=sub, email=email if isinstance(email, str) else None)

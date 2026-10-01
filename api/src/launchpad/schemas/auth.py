from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import EmailStr, Field

from launchpad.schemas.common import Schema


class RegisterIn(Schema):
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)
    name: str | None = Field(default=None, max_length=120)


class LoginIn(Schema):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class UserOut(Schema):
    id: uuid.UUID
    email: str
    name: str | None
    created_at: datetime


class SessionOut(Schema):
    user: UserOut
    # Also returned in the body for non-browser clients; browsers use the httpOnly cookie.
    access_token: str
    token_type: str = "bearer"  # noqa: S105

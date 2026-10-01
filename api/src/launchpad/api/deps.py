from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from launchpad.api.errors import NotFound, Unauthorized
from launchpad.config import get_settings
from launchpad.db.session import get_db
from launchpad.models import User, Workspace
from launchpad.security.tokens import InvalidToken, verify_token

SESSION_COOKIE = "lp_session"

DB = Annotated[AsyncSession, Depends(get_db)]


def _extract_token(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip() or None
    return request.cookies.get(SESSION_COOKIE)


async def get_current_user(request: Request, db: DB) -> User:
    token = _extract_token(request)
    if not token:
        raise Unauthorized("Not signed in.")
    try:
        claims = verify_token(token)
    except InvalidToken as exc:
        raise Unauthorized("Session is invalid or expired.") from exc

    user: User | None
    if get_settings().auth_provider == "supabase":
        user = await db.scalar(select(User).where(User.external_auth_id == claims.subject))
        if user is None:
            # First request from a Supabase user: provision a local profile row.
            if not claims.email:
                raise Unauthorized("Token has no email claim.")
            user = User(email=claims.email.lower(), external_auth_id=claims.subject)
            db.add(user)
            await db.commit()
    else:
        try:
            user = await db.get(User, uuid.UUID(claims.subject))
        except ValueError as exc:
            raise Unauthorized("Session is invalid.") from exc
        if user is None:
            raise Unauthorized("Account no longer exists.")

    request.state.user_id = str(user.id)
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def get_workspace(workspace_id: uuid.UUID, user: CurrentUser, db: DB) -> Workspace:
    """Resolves a workspace the current user owns. 404 (not 403) to avoid leaking existence."""
    ws = await db.get(Workspace, workspace_id)
    if ws is None or ws.owner_id != user.id:
        raise NotFound("Workspace not found.")
    return ws


CurrentWorkspace = Annotated[Workspace, Depends(get_workspace)]

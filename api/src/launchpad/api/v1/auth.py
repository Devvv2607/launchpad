from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from launchpad.api.deps import DB, SESSION_COOKIE, CurrentUser
from launchpad.api.errors import AppError, Conflict, Unauthorized
from launchpad.api.ratelimit import rate_limit
from launchpad.config import get_settings
from launchpad.models import User
from launchpad.schemas.auth import LoginIn, RegisterIn, SessionOut, UserOut
from launchpad.security.passwords import hash_password, verify_password
from launchpad.security.tokens import issue_token

router = APIRouter(prefix="/auth", tags=["auth"])

# A valid hash to verify against when the email is unknown, so response time doesn't
# reveal whether an account exists.
_DUMMY_HASH = hash_password("dummy-password-for-timing")


def _local_only() -> None:
    if get_settings().auth_provider != "local":
        raise AppError("Password auth is disabled; sign in with the configured provider.")


def _set_session_cookie(response: Response, token: str) -> None:
    s = get_settings()
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=s.jwt_ttl_minutes * 60,
        httponly=True,
        secure=s.env == "prod",
        samesite="lax",
        path="/",
    )


@router.post(
    "/register",
    response_model=SessionOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(_local_only), Depends(rate_limit("auth", 10, 60))],
)
async def register(body: RegisterIn, response: Response, db: DB) -> SessionOut:
    user = User(
        email=body.email.lower(), name=body.name, password_hash=hash_password(body.password)
    )
    db.add(user)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise Conflict("An account with this email already exists.") from exc
    await db.refresh(user)
    token = issue_token(user.id, user.email)
    _set_session_cookie(response, token)
    return SessionOut(user=UserOut.model_validate(user), access_token=token)


@router.post(
    "/login",
    response_model=SessionOut,
    dependencies=[Depends(_local_only), Depends(rate_limit("auth", 10, 60))],
)
async def login(body: LoginIn, response: Response, db: DB) -> SessionOut:
    user = await db.scalar(select(User).where(User.email == body.email.lower()))
    if user is None or not user.password_hash:
        verify_password(_DUMMY_HASH, body.password)
        raise Unauthorized("Incorrect email or password.")
    if not verify_password(user.password_hash, body.password):
        raise Unauthorized("Incorrect email or password.")
    token = issue_token(user.id, user.email)
    _set_session_cookie(response, token)
    return SessionOut(user=UserOut.model_validate(user), access_token=token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> User:
    return user

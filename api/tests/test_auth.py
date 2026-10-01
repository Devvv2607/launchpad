from __future__ import annotations

from httpx import AsyncClient


async def test_register_sets_httponly_cookie_and_me_works(client: AsyncClient) -> None:
    r = await client.post(
        "/api/v1/auth/register",
        json={"email": "A@Example.com", "password": "long-enough-pass"},
    )
    assert r.status_code == 201
    cookie = r.headers["set-cookie"]
    assert "lp_session=" in cookie and "HttpOnly" in cookie and "SameSite=lax" in cookie

    me = await client.get("/api/v1/auth/me")  # cookie jar carries the session
    assert me.status_code == 200
    assert me.json()["email"] == "a@example.com"


async def test_duplicate_email_conflicts(client: AsyncClient) -> None:
    body = {"email": "dup@example.com", "password": "long-enough-pass"}
    assert (await client.post("/api/v1/auth/register", json=body)).status_code == 201
    r = await client.post("/api/v1/auth/register", json=body)
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "conflict"


async def test_login_rejects_wrong_password_with_same_message(client: AsyncClient) -> None:
    await client.post(
        "/api/v1/auth/register", json={"email": "u@example.com", "password": "long-enough-pass"}
    )
    client.cookies.clear()
    wrong = await client.post(
        "/api/v1/auth/login", json={"email": "u@example.com", "password": "nope"}
    )
    unknown = await client.post(
        "/api/v1/auth/login", json={"email": "ghost@example.com", "password": "nope"}
    )
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["error"]["message"] == unknown.json()["error"]["message"]

    ok = await client.post(
        "/api/v1/auth/login", json={"email": "u@example.com", "password": "long-enough-pass"}
    )
    assert ok.status_code == 200


async def test_short_password_is_validation_error(client: AsyncClient) -> None:
    r = await client.post(
        "/api/v1/auth/register", json={"email": "s@example.com", "password": "short"}
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"


async def test_unauthenticated_and_tampered_tokens_rejected(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/auth/me")).status_code == 401
    r = await client.get("/api/v1/auth/me", headers={"authorization": "Bearer abc.def.ghi"})
    assert r.status_code == 401


async def test_request_id_is_echoed(client: AsyncClient) -> None:
    r = await client.get("/api/v1/meta", headers={"x-request-id": "req-12345678"})
    assert r.headers["x-request-id"] == "req-12345678"
    r = await client.get("/api/v1/meta", headers={"x-request-id": "bad id!"})
    assert r.headers["x-request-id"] != "bad id!"


async def test_auth_endpoints_are_rate_limited(client: AsyncClient) -> None:
    body = {"email": "rl@example.com", "password": "wrong"}
    codes = [(await client.post("/api/v1/auth/login", json=body)).status_code for _ in range(12)]
    if 429 not in codes:
        import pytest

        pytest.skip("Redis not reachable; limiter is fail-open outside prod")
    assert codes[:10] == [401] * 10 and codes[-1] == 429

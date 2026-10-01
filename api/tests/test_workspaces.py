from __future__ import annotations

from httpx import AsyncClient

WS = {
    "name": "Chai & Chapter",
    "industry": "food",
    "audience": "Students and young professionals in Bandra",
    "locations": ["Mumbai"],
    "website": "https://example.com",
}


async def test_workspace_crud_and_brand_kit(authed: AsyncClient) -> None:
    r = await authed.post("/api/v1/workspaces", json=WS)
    assert r.status_code == 201, r.text
    ws = r.json()
    assert ws["timezone"] == "Asia/Kolkata"

    listed = (await authed.get("/api/v1/workspaces")).json()
    assert [w["id"] for w in listed] == [ws["id"]]

    r = await authed.patch(f"/api/v1/workspaces/{ws['id']}", json={"audience": "Everyone"})
    assert r.json()["audience"] == "Everyone"

    kit = (await authed.get(f"/api/v1/workspaces/{ws['id']}/brand-kit")).json()
    assert kit["primary_color"] is None

    r = await authed.put(
        f"/api/v1/workspaces/{ws['id']}/brand-kit",
        json={"primary_color": "#aa5500", "voice_tone": "Warm, witty", "do_words": ["chai"]},
    )
    assert r.status_code == 200
    assert r.json()["primary_color"] == "#AA5500"

    bad = await authed.put(
        f"/api/v1/workspaces/{ws['id']}/brand-kit", json={"primary_color": "orange"}
    )
    assert bad.status_code == 422

    assert (await authed.delete(f"/api/v1/workspaces/{ws['id']}")).status_code == 204
    assert (await authed.get(f"/api/v1/workspaces/{ws['id']}")).status_code == 404


async def test_invalid_industry_and_timezone(authed: AsyncClient) -> None:
    r = await authed.post("/api/v1/workspaces", json={**WS, "industry": "crypto"})
    assert r.status_code == 422
    r = await authed.post("/api/v1/workspaces", json={**WS, "timezone": "Mars/Olympus"})
    assert r.status_code == 422


async def test_users_cannot_see_each_others_workspaces(authed: AsyncClient) -> None:
    ws = (await authed.post("/api/v1/workspaces", json=WS)).json()

    other = await authed.post(
        "/api/v1/auth/register",
        json={"email": "intruder@example.com", "password": "long-enough-pass"},
    )
    authed.headers["authorization"] = f"Bearer {other.json()['access_token']}"

    assert (await authed.get(f"/api/v1/workspaces/{ws['id']}")).status_code == 404
    assert (await authed.get("/api/v1/workspaces")).json() == []
    r = await authed.put(f"/api/v1/workspaces/{ws['id']}/brand-kit", json={})
    assert r.status_code == 404


async def test_body_size_limit(authed: AsyncClient) -> None:
    huge = "x" * (11 * 1024 * 1024)
    r = await authed.post("/api/v1/workspaces", json={**WS, "description": huge})
    assert r.status_code == 413


async def test_browser_timezone_aliases_are_accepted(authed: AsyncClient) -> None:
    # Chrome on Windows reports the legacy alias; needs the tzdata package on Windows hosts.
    r = await authed.post("/api/v1/workspaces", json={**WS, "timezone": "Asia/Calcutta"})
    assert r.status_code == 201, r.text

from __future__ import annotations

import io

from httpx import AsyncClient
from PIL import Image, ImageDraw

from launchpad.services.colors import contrast_ratio, extract_palette, hex_to_rgb, wcag_rating

WS = {"name": "Chai & Chapter", "industry": "food"}


def logo_png(transparent: bool = True) -> bytes:
    """Synthetic logo: transparent (or white) canvas, a big navy disc, a marigold bar,
    a small teal dot, and black text-like strokes that must be ignored."""
    bg = (0, 0, 0, 0) if transparent else (255, 255, 255, 255)
    img = Image.new("RGBA", (400, 400), bg)
    d = ImageDraw.Draw(img)
    d.ellipse((40, 40, 300, 300), fill=(30, 34, 80, 255))  # navy, dominant
    d.rectangle((40, 320, 360, 370), fill=(240, 160, 32, 255))  # marigold
    d.ellipse((320, 40, 370, 90), fill=(0, 150, 136, 255))  # teal accent
    d.line((60, 380, 340, 380), fill=(5, 5, 5, 255), width=6)  # near-black: ignored
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def test_wcag_contrast_reference_values() -> None:
    assert contrast_ratio((255, 255, 255), (0, 0, 0)) == 21.0
    assert contrast_ratio(hex_to_rgb("#767676"), (255, 255, 255)) == 4.54  # classic AA grey
    assert wcag_rating(4.54) == "AA" and wcag_rating(3.2) == "AA large" and wcag_rating(2) == "fail"


def test_palette_ignores_background_and_assigns_roles() -> None:
    for transparent in (True, False):
        img = Image.open(io.BytesIO(logo_png(transparent)))
        palette = extract_palette(img)
        hexes = [p.hex for p in palette]
        assert palette[0].role == "primary" and _close(palette[0].hex, "#1E2250")
        assert any(_close(h, "#F0A020") for h in hexes)
        assert not any(min(hex_to_rgb(h)) > 235 or max(hex_to_rgb(h)) < 28 for h in hexes)
        roles = {p.role for p in palette}
        assert {"primary", "secondary"} <= roles
        navy = palette[0]
        assert navy.best_text == "#FFFFFF" and navy.rating_on_white in ("AA", "AAA")
        assert abs(sum(p.share for p in palette) - 1) < 0.01


def test_all_background_logo_yields_no_suggestions() -> None:
    img = Image.new("RGBA", (50, 50), (255, 255, 255, 255))
    assert extract_palette(img) == []


def _close(a: str, b: str, tol: int = 24) -> bool:
    return all(abs(x - y) <= tol for x, y in zip(hex_to_rgb(a), hex_to_rgb(b), strict=True))


async def _ws(client: AsyncClient) -> str:
    r = await client.post("/api/v1/workspaces", json=WS)
    return str(r.json()["id"])


async def test_logo_upload_stores_variants_suggests_but_never_overwrites(
    authed: AsyncClient,
) -> None:
    ws = await _ws(authed)
    await authed.put(f"/api/v1/workspaces/{ws}/brand-kit", json={"primary_color": "#123456"})

    r = await authed.post(
        f"/api/v1/workspaces/{ws}/brand-kit/logo",
        files={"file": ("logo.png", logo_png(), "image/png")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["has_existing_colors"] is True
    assert body["palette"][0]["role"] == "primary"
    assert body["logo"]["variant"] == "normalized" and body["thumbnail"]["width"] <= 256

    kit = (await authed.get(f"/api/v1/workspaces/{ws}/brand-kit")).json()
    assert kit["primary_color"] == "#123456"  # untouched
    assert kit["logo_palette"] and kit["logo_url"]

    # Signed URL serves the PNG; a tampered signature is refused.
    img = await authed.get(kit["logo_url"])
    assert img.status_code == 200 and img.headers["content-type"] == "image/png"
    assert img.headers["x-content-type-options"] == "nosniff"
    bad = await authed.get(kit["logo_url"].replace("sig=", "sig=0"))
    assert bad.status_code == 403

    assets = (await authed.get(f"/api/v1/workspaces/{ws}/assets?kind=logo")).json()
    assert len(assets) == 1  # variants hidden by default
    every = (await authed.get(f"/api/v1/workspaces/{ws}/assets?include_variants=true")).json()
    assert {a["variant"] for a in every} == {"original", "normalized", "thumbnail"}


async def test_upload_rejections_are_specific(authed: AsyncClient) -> None:
    ws = await _ws(authed)
    url = f"/api/v1/workspaces/{ws}/brand-kit/logo"
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><rect width="10" height="10"/></svg>'
    r = await authed.post(url, files={"file": ("logo.svg", svg, "image/svg+xml")})
    assert r.status_code == 415 and "PNG" in r.json()["error"]["message"]

    r = await authed.post(url, files={"file": ("fake.png", b"not really an image", "image/png")})
    assert r.status_code == 415

    big = b"\x89PNG" + b"0" * (5 * 1024 * 1024 + 10)
    r = await authed.post(url, files={"file": ("huge.png", big, "image/png")})
    assert r.status_code == 413 and "5 MB" in r.json()["error"]["message"]


async def test_assets_are_workspace_scoped(authed: AsyncClient) -> None:
    ws = await _ws(authed)
    r = await authed.post(
        f"/api/v1/workspaces/{ws}/brand-kit/logo",
        files={"file": ("l.png", logo_png(), "image/png")},
    )
    asset_id = r.json()["logo"]["parent_id"]

    other = await authed.post(
        "/api/v1/auth/register", json={"email": "other@example.com", "password": "long-enough-pass"}
    )
    authed.headers["authorization"] = f"Bearer {other.json()['access_token']}"
    other_ws = await _ws(authed)
    r = await authed.delete(f"/api/v1/workspaces/{other_ws}/assets/{asset_id}")
    assert r.status_code == 404

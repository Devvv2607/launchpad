from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from launchpad.config import get_settings
from launchpad.content.engine import write_content
from launchpad.db.session import get_sessionmaker
from launchpad.domain.enums import Channel
from launchpad.llm import service as llm_service
from launchpad.llm.errors import LLMAuthError, LLMOutputError
from launchpad.llm.service import CallContext
from launchpad.models import ContentItem, LLMCall, User, Workspace
from tests.content.fake_llm import THREE, ScriptedLLM, critique, drafts, ig_variant


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    s = get_settings()
    for k, v in {
        "llm_provider": "gemini", "llm_model": "gemini-3.6-flash", "llm_fast_model": "gemini-3.1-flash-lite",
        "embedding_provider": "gemini", "embedding_model": "gemini-embedding-001", "daily_spend_cap_usd": 100.0,
    }.items():  # fmt: skip
        monkeypatch.setattr(s, k, v)


def use(monkeypatch: pytest.MonkeyPatch, fake: ScriptedLLM) -> ScriptedLLM:
    monkeypatch.setattr(llm_service.llm, "_client_factory", lambda _p: fake)
    return fake


async def _ws() -> tuple[Workspace, CallContext]:
    async with get_sessionmaker()() as db:
        user = User(email=f"{uuid.uuid4().hex}@example.com")
        db.add(user)
        await db.flush()
        ws = Workspace(
            owner_id=user.id, name="Chai & Chapter", industry="food", locations=["Mumbai"]
        )
        db.add(ws)
        await db.commit()
        return ws, CallContext.for_workspace(ws, user.id)


async def test_three_distinct_variants_reviewed_and_saved(monkeypatch: pytest.MonkeyPatch) -> None:
    def script(kind: str, prompt: str) -> str:
        if kind == "write":
            return THREE
        draft = json.loads(prompt.split("Draft (JSON):\n", 1)[1].split("\n\nAutomated", 1)[0])
        return critique(9, draft)

    fake = use(monkeypatch, ScriptedLLM(script))
    ws, ctx = await _ws()
    events: list[dict[str, Any]] = []

    async def progress(e: dict[str, Any]) -> None:
        events.append(e)

    async with get_sessionmaker()() as db:
        ws = await db.get(Workspace, ws.id)  # type: ignore[assignment]
        results = await write_content(
            db,
            ws,
            ctx,
            channel=Channel.INSTAGRAM_POST,
            brief="Monsoon chai + pakora offer",
            progress=progress,
        )
    assert [r.label for r in results] == ["A", "B", "C"]
    assert len({r.angle for r in results}) == 3
    # Good scores on round 1 → no revision → exactly one critique per variant.
    assert [k for k, _ in fake.calls].count("critique") == 3
    assert all(len(r.iterations) == 1 and r.iterations[0].scores for r in results)

    labels = [e["label"] for e in events if e.get("type") == "step" and e["status"] == "running"]
    assert labels[:3] == ["Reading brand kit", "Retrieving brand docs", "Writing 3 variants"]
    assert any(lbl.startswith("Reviewing variant A") for lbl in labels)
    assert events[-1]["label"] == "Saved as drafts"

    async with get_sessionmaker()() as db:
        items = list(await db.scalars(select(ContentItem).where(ContentItem.workspace_id == ws.id)))
        calls = {c.id: c for c in await db.scalars(select(LLMCall))}
    assert len(items) == 3 and len({i.variant_group for i in items}) == 1
    item = next(i for i in items if i.variant_label == "A")
    assert item.status == "draft" and item.critique_score == 9
    assert item.hashtags == ["#MumbaiRains", "#chai", "#Bandra"]
    gen = item.generation
    assert gen["brief"] == "Monsoon chai + pakora offer" and gen["angle"] == "Rainy-day nostalgia"
    assert gen["prompt_versions"]["write_content"].startswith("2026-")
    linked = [calls[uuid.UUID(cid)] for cid in gen["llm_call_ids"]]
    assert {c.purpose for c in linked} == {"write_content", "critique_content"}
    assert all(c.workspace_id == ws.id for c in linked)


async def test_low_scores_revise_at_most_twice_and_keep_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rounds = {"n": 0}

    def script(kind: str, prompt: str) -> str:
        if kind == "write":
            return drafts(ig_variant("Rainy-day nostalgia", "Remember school chai breaks?"))
        rounds["n"] += 1
        revised = ig_variant(
            "x", "y", caption=f"Revision {rounds['n']}: chai + pakoras. Visit today."
        )["content"]
        return critique(6, revised)

    use(monkeypatch, ScriptedLLM(script))
    ws, ctx = await _ws()
    async with get_sessionmaker()() as db:
        ws = await db.get(Workspace, ws.id)  # type: ignore[assignment]
        [r] = await write_content(
            db, ws, ctx, channel=Channel.INSTAGRAM_POST, brief="Monsoon", n_variants=1
        )
    assert rounds["n"] == 2  # never more than 2 critique rounds
    assert [it.round for it in r.iterations] == [0, 1, 2]
    assert r.iterations[0].scores and r.iterations[1].scores and r.iterations[2].scores is None
    assert r.iterations[0].issues == ["CTA is vague"]
    assert r.content["caption"].startswith("Revision 2")


async def test_violations_are_fed_back_and_flag_if_unfixed(monkeypatch: pytest.MonkeyPatch) -> None:
    seen_prompts: list[str] = []
    too_long = "Monsoon special. " + "Chai and pakoras. " * 150  # > 2200 chars

    def script(kind: str, prompt: str) -> str:
        if kind == "write":
            return drafts(ig_variant("Offer-led", "Monsoon menu is here", caption=too_long))
        seen_prompts.append(prompt)
        return critique(
            9, ig_variant("Offer-led", "x", caption=too_long)["content"]
        )  # "fix" that isn't

    use(monkeypatch, ScriptedLLM(script))
    ws, ctx = await _ws()
    async with get_sessionmaker()() as db:
        ws = await db.get(Workspace, ws.id)  # type: ignore[assignment]
        [r] = await write_content(
            db, ws, ctx, channel=Channel.INSTAGRAM_POST, brief="Monsoon", n_variants=1
        )
    # A 9/10 doesn't count as done while a hard platform limit is broken.
    assert len(seen_prompts) == 2
    assert "MUST fix" in seen_prompts[0] and "the limit is 2200" in seen_prompts[0]
    assert r.blocked and r.violations[0]["rule"] == "max_chars"
    assert len(r.content["caption"]) > 2200  # never silently truncated


async def test_duplicate_angles_are_repaired_or_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    dup = drafts(
        ig_variant("Offer-led", "Monsoon menu is here with chai"),
        ig_variant("Offer-led", "Our monsoon menu is here with chai"),
    )
    fake = use(monkeypatch, ScriptedLLM(lambda kind, prompt: dup))
    ws, ctx = await _ws()
    async with get_sessionmaker()() as db:
        ws = await db.get(Workspace, ws.id)  # type: ignore[assignment]
        with pytest.raises(LLMOutputError) as exc:
            await write_content(
                db, ws, ctx, channel=Channel.INSTAGRAM_POST, brief="Monsoon", n_variants=2
            )
    assert "different angle" in exc.value.details["errors"]
    assert len(fake.calls) == 2  # initial + one repair, then a typed error — no fallback copy
    async with get_sessionmaker()() as db:
        assert not list(
            await db.scalars(select(ContentItem).where(ContentItem.workspace_id == ws.id))
        )


def _parse_sse(raw: str) -> list[tuple[str, dict[str, Any]]]:
    out = []
    for block in raw.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines() if not line.startswith(":"))
        if "event" in lines:
            out.append((lines["event"], json.loads(lines["data"])))
    return out


async def test_generate_endpoint_streams_steps_items_and_done(
    authed: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def script(kind: str, prompt: str) -> str:
        if kind == "write":
            return THREE
        return critique(9, json.loads(prompt.split("Draft (JSON):\n", 1)[1]))

    use(monkeypatch, ScriptedLLM(script))
    ws = (
        await authed.post("/api/v1/workspaces", json={"name": "Chai", "industry": "food"})
    ).json()["id"]
    r = await authed.post(
        f"/api/v1/workspaces/{ws}/content/generate",
        json={"channel": "instagram_post", "brief": "Monsoon chai offer", "n_variants": 3},
    )
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    events = _parse_sse(r.text)
    kinds = [e for e, _ in events]
    assert kinds[0] == "step" and kinds[-1] == "done"
    assert kinds.count("item") == 3 and kinds.count("variant") == 3
    item = next(d for e, d in events if e == "item")
    assert (
        item["status"] == "draft" and item["blocked"] is False and item["generation"]["iterations"]
    )

    listed = (await authed.get(f"/api/v1/workspaces/{ws}/content?status=draft")).json()
    assert len(listed) == 3


async def test_generate_endpoint_streams_typed_errors(
    authed: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    use(
        monkeypatch,
        ScriptedLLM(
            lambda k, p: LLMAuthError(
                "Gemini rejected the API key (400).", hint="Check GEMINI_API_KEY in .env."
            )
        ),
    )
    ws = (
        await authed.post("/api/v1/workspaces", json={"name": "Chai", "industry": "food"})
    ).json()["id"]
    r = await authed.post(
        f"/api/v1/workspaces/{ws}/content/generate",
        json={"channel": "linkedin_post", "brief": "Hiring baristas"},
    )
    events = _parse_sse(r.text)
    event, data = events[-1]
    assert event == "error" and data["code"] == "llm_auth" and "GEMINI_API_KEY" in data["hint"]
    assert not (await authed.get(f"/api/v1/workspaces/{ws}/content")).json()


async def test_edit_revalidates_and_regenerate_keeps_history(
    authed: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = {"writes": 0}

    def script(kind: str, prompt: str) -> str:
        if kind == "write":
            state["writes"] += 1
            if state["writes"] == 1:
                return drafts(ig_variant("Offer-led", "Monsoon menu is here"))
            return drafts(ig_variant("Offer-led", "Fresh take: monsoon menu"))
        return critique(
            9, json.loads(prompt.split("Draft (JSON):\n", 1)[1].split("\n\nAutomated", 1)[0])
        )

    use(monkeypatch, ScriptedLLM(script))
    ws = (
        await authed.post("/api/v1/workspaces", json={"name": "Chai", "industry": "food"})
    ).json()["id"]
    r = await authed.post(
        f"/api/v1/workspaces/{ws}/content/generate",
        json={"channel": "instagram_post", "brief": "Monsoon chai offer", "n_variants": 1},
    )
    item = next(d for e, d in _parse_sse(r.text) if e == "item")
    url = f"/api/v1/workspaces/{ws}/content/{item['id']}"

    content = {k: v for k, v in item["payload"].items()}
    content["caption"] = "x" * 2300
    edited = (await authed.patch(url, json={"content": content})).json()
    assert edited["blocked"] is True and edited["violations"][0]["rule"] == "max_chars"

    bad = await authed.patch(url, json={"content": {"caption": "missing fields"}})
    assert bad.status_code == 400

    regen = (await authed.post(f"{url}/regenerate")).json()
    assert regen["generation"]["hook"] == "Fresh take: monsoon menu"
    assert len(regen["generation"]["history"]) == 1 and regen["blocked"] is False


async def test_email_items_store_sanitised_html_and_text(
    authed: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    email = {
        "subject_variants": [
            "Monsoon chai is back",
            "Rain, chai, books",
            "Your Sunday reading spot",
        ],
        "preheader": "Masala chai and pakoras all week at Chai & Chapter in Bandra.",
        "sections": [
            {
                "type": "hero",
                "heading": "Monsoon <b>menu</b>",
                "body": "Chai + pakoras.",
                "items": [],
                "button_label": None,
                "button_url": None,
            },
            {
                "type": "cta",
                "heading": None,
                "body": None,
                "items": [],
                "button_label": "Reserve a table",
                "button_url": "javascript:alert(1)",
            },
        ],
    }
    variant = {
        "angle": "Cosy monsoon",
        "hook": "Rain + chai",
        "rationale": "Seasonal",
        "content": email,
    }

    def script(kind: str, prompt: str) -> str:
        return json.dumps({"variants": [variant]}) if kind == "write" else critique(9, email)

    use(monkeypatch, ScriptedLLM(script))
    ws = (
        await authed.post(
            "/api/v1/workspaces",
            json={"name": "Chai", "industry": "food", "website": "https://chai.example"},
        )
    ).json()["id"]
    r = await authed.post(
        f"/api/v1/workspaces/{ws}/content/generate",
        json={"channel": "email", "brief": "Monsoon newsletter", "n_variants": 1},
    )
    item = next(d for e, d in _parse_sse(r.text) if e == "item")
    html, text = item["payload"]["rendered"]["html"], item["payload"]["rendered"]["text"]
    assert "&lt;b&gt;menu&lt;/b&gt;" in html and "javascript:" not in html
    assert (
        'href="https://chai.example/"' in html and "Reserve a table: https://chai.example/" in text
    )
    assert (
        html.startswith("<!doctype html>") and "<body" in html and '<meta name="viewport"' in html
    )
    assert item["body"] == "Monsoon chai is back"


def test_brief_facts_extracts_prices_and_percentages() -> None:
    from launchpad.content.engine import brief_facts

    assert brief_facts("Monsoon drop: 5 tees, ₹699 each, bundle Rs. 1,899, 15% off") == [
        ("₹699", "699"),
        ("Rs. 1,899", "1899"),
        ("15%", "15%"),
    ]
    assert brief_facts("New collection drop") == []


async def test_missing_brief_price_triggers_a_revision(monkeypatch: pytest.MonkeyPatch) -> None:
    brief = "Monsoon chai with pakoras, ₹160"
    no_price = ig_variant("Offer-led", "Monsoon menu is here")
    with_price = ig_variant(
        "Offer-led", "Monsoon menu is here", caption="Masala chai + pakoras, ₹160. Drop in."
    )
    critiques: list[str] = []

    def script(kind: str, prompt: str) -> str:
        if kind == "write":
            return drafts(no_price)
        critiques.append(prompt)
        return critique(9, with_price["content"])

    use(monkeypatch, ScriptedLLM(script))
    ws, ctx = await _ws()
    async with get_sessionmaker()() as db:
        ws = await db.get(Workspace, ws.id)
        assert ws is not None
        [v] = await write_content(
            db, ws, ctx, channel=Channel.INSTAGRAM_POST, brief=brief, n_variants=1
        )
    assert "₹160" in critiques[0]  # the critic is told what's missing
    assert len(v.iterations) == 2  # scores were 9, but the missing price forced a revision
    assert "₹160" in v.content["caption"]
    assert not [x for x in v.violations if x["rule"] == "brief_fact_missing"]

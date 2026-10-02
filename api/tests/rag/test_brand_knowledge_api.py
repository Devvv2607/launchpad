from __future__ import annotations

import json
import uuid
from collections.abc import Iterator

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from launchpad.config import get_settings
from launchpad.db.session import get_sessionmaker
from launchpad.domain.enums import JobKind, JobStatus
from launchpad.jobs import queue as queue_mod
from launchpad.jobs.handlers import ingest_document
from launchpad.llm import service as llm_service
from launchpad.models import LLMCall, ScheduledJob
from tests.rag.fakes import FakeEmbedder

BRAND_MD = """# Our story
Chai & Chapter is a bookshop cafe in Bandra, Mumbai, opened in 2019 by two friends who
loved books and cutting chai. Every table has a shelf of second-hand novels you can read.

# Menu
We serve cutting chai brewed over charcoal, filter coffee, bun maska and Irani chai.
Our monsoon special is masala chai with pakoras.

# Events
Every Sunday morning we host a silent reading circle. Poetry open mic on the last Friday.
"""


@pytest.fixture
def fake_llm(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeEmbedder]:
    s = get_settings()
    for attr, value in {
        "embedding_provider": "gemini",
        "embedding_model": "gemini-embedding-001",
        "llm_provider": "gemini",
        "llm_model": "gemini-3.6-flash",
        "rag_min_score": 0.2,
    }.items():
        monkeypatch.setattr(s, attr, value)
    fake = FakeEmbedder()
    monkeypatch.setattr(llm_service.llm, "_client_factory", lambda _p: fake)

    async def no_poke(_job_id: uuid.UUID) -> None:
        return None

    monkeypatch.setattr(queue_mod, "_poke_worker", no_poke)
    yield fake


async def _ws(client: AsyncClient) -> str:
    return str(
        (await client.post("/api/v1/workspaces", json={"name": "Chai", "industry": "food"})).json()[
            "id"
        ]
    )


async def _run_jobs() -> None:
    """Run pending ingest jobs exactly like the worker does."""
    async with get_sessionmaker()() as db:
        jobs = list(
            await db.scalars(select(ScheduledJob).where(ScheduledJob.status == JobStatus.PENDING))
        )
        for job in jobs:
            job.attempts += 1
            await ingest_document(db, job)
            job.status = JobStatus.SUCCEEDED
            await db.commit()


async def test_upload_ingest_and_retrieve_with_citations(
    authed: AsyncClient, fake_llm: FakeEmbedder
) -> None:
    ws = await _ws(authed)
    r = await authed.post(
        f"/api/v1/workspaces/{ws}/brand-docs",
        files={"file": ("brand.md", BRAND_MD.encode(), "text/markdown")},
    )
    assert r.status_code == 202 and r.json()["status"] == "pending"

    async with get_sessionmaker()() as db:
        [job] = list(await db.scalars(select(ScheduledJob)))
        assert job.kind == JobKind.INGEST_DOCUMENT

    await _run_jobs()
    [doc] = (await authed.get(f"/api/v1/workspaces/{ws}/brand-docs")).json()
    assert doc["status"] == "ready" and doc["chunk_count"] >= 3
    assert doc["embedding_model"] == "gemini-embedding-001" and doc["needs_reindex"] is False

    r = await authed.post(
        f"/api/v1/workspaces/{ws}/brand-docs/search",
        json={"query": "what happens on Sunday reading circle", "k": 3},
    )
    body = r.json()
    top = body["chunks"][0]
    assert top["heading"] == "Events" and top["source"] == "brand.md"
    assert 0 < top["score"] <= 1
    assert [c["score"] for c in body["chunks"]] == sorted(
        (c["score"] for c in body["chunks"]), reverse=True
    )

    # Irrelevant query: everything falls below the threshold, nothing is invented.
    r = await authed.post(
        f"/api/v1/workspaces/{ws}/brand-docs/search", json={"query": "quantum tax law"}
    )
    assert r.json()["chunks"] == [] and r.json()["dropped_below_threshold"] >= 1

    # Embedding calls are logged for usage/cost.
    async with get_sessionmaker()() as db:
        purposes = {c.purpose for c in await db.scalars(select(LLMCall))}
    assert {"embed_document", "embed_query"} <= purposes


async def test_model_change_flags_reindex_and_excludes_stale(
    authed: AsyncClient, fake_llm: FakeEmbedder, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = await _ws(authed)
    await authed.post(
        f"/api/v1/workspaces/{ws}/brand-docs",
        files={"file": ("brand.md", BRAND_MD.encode(), "text/markdown")},
    )
    await _run_jobs()
    monkeypatch.setattr(get_settings(), "embedding_model", "gemini-embedding-2-preview")

    status = (await authed.get(f"/api/v1/workspaces/{ws}/brand-index")).json()
    assert status["needs_reindex"] is True and status["stale_documents"] == 1
    [doc] = (await authed.get(f"/api/v1/workspaces/{ws}/brand-docs")).json()
    assert doc["needs_reindex"] is True
    r = await authed.post(
        f"/api/v1/workspaces/{ws}/brand-docs/search", json={"query": "Sunday reading circle"}
    )
    assert r.json()["chunks"] == []  # vectors from another model are never compared

    r = await authed.post(f"/api/v1/workspaces/{ws}/brand-index/reindex")
    assert r.status_code == 202 and len(r.json()) == 1
    await _run_jobs()
    assert (await authed.get(f"/api/v1/workspaces/{ws}/brand-index")).json()[
        "needs_reindex"
    ] is False
    r = await authed.post(
        f"/api/v1/workspaces/{ws}/brand-docs/search", json={"query": "Sunday reading circle"}
    )
    assert r.json()["chunks"]


async def test_failed_extraction_is_reported_on_the_document(
    authed: AsyncClient, fake_llm: FakeEmbedder
) -> None:
    ws = await _ws(authed)
    r = await authed.post(
        f"/api/v1/workspaces/{ws}/brand-docs",
        files={"file": ("scan.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")},
    )
    assert r.status_code == 202
    from launchpad.jobs import PermanentJobError

    with pytest.raises(PermanentJobError):
        await _run_jobs()
    [doc] = (await authed.get(f"/api/v1/workspaces/{ws}/brand-docs")).json()
    assert doc["status"] == "failed" and doc["error"]


async def test_unsupported_and_private_url_inputs(
    authed: AsyncClient, fake_llm: FakeEmbedder
) -> None:
    ws = await _ws(authed)
    r = await authed.post(
        f"/api/v1/workspaces/{ws}/brand-docs",
        files={"file": ("x.exe", b"MZ\x90\x00", "application/octet-stream")},
    )
    assert r.status_code == 415
    r = await authed.post(
        f"/api/v1/workspaces/{ws}/brand-docs/url", json={"url": "http://127.0.0.1:8000/"}
    )
    assert r.status_code == 400 and "private" in r.json()["error"]["message"]


VOICE = {
    "summary": "Warm and bookish, with gentle humour. Talks like a regular who knows the staff.",
    "tone_adjectives": ["warm", "bookish", "playful"],
    "formality": 2,
    "sentence_length": "short",
    "emoji_usage": "rare",
    "do_words": ["cutting chai"],
    "dont_words": [],
    "signature_phrases": ["See you at the shelf"],
}
SAMPLES = [
    "Rainy day? Cutting chai + a novel. See you at the shelf.",
    "Sunday reading circle is back!",
    "Bun maska restocked.",
]


async def test_voice_profile_from_samples(authed: AsyncClient, fake_llm: FakeEmbedder) -> None:
    ws = await _ws(authed)
    fake_llm.replies = [json.dumps(VOICE)]
    r = await authed.post(
        f"/api/v1/workspaces/{ws}/brand-kit/voice-profile", json={"samples": SAMPLES}
    )
    assert r.status_code == 200, r.text
    kit = (await authed.get(f"/api/v1/workspaces/{ws}/brand-kit")).json()
    assert kit["voice_profile"]["formality"] == 2 and kit["sample_posts"] == SAMPLES

    # A later brand-kit save without the profile must not wipe it.
    await authed.put(f"/api/v1/workspaces/{ws}/brand-kit", json={"voice_tone": "Warm"})
    kit = (await authed.get(f"/api/v1/workspaces/{ws}/brand-kit")).json()
    assert kit["voice_profile"]["tone_adjectives"] == ["warm", "bookish", "playful"]


async def test_voice_profile_invalid_output_surfaces_error(
    authed: AsyncClient, fake_llm: FakeEmbedder
) -> None:
    ws = await _ws(authed)
    bad = json.dumps({**VOICE, "formality": 9})
    fake_llm.replies = [bad, bad]
    r = await authed.post(
        f"/api/v1/workspaces/{ws}/brand-kit/voice-profile", json={"samples": SAMPLES}
    )
    assert r.status_code == 502
    err = r.json()["error"]
    assert err["code"] == "llm_invalid_output" and err["details"]["hint"]
    kit = (await authed.get(f"/api/v1/workspaces/{ws}/brand-kit")).json()
    assert kit["voice_profile"] is None  # nothing fake was saved

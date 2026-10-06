"""The eval runner itself: --smoke selection and stopping cleanly when quota runs out."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from launchpad.agent.research import set_search_provider
from launchpad.config import get_settings
from launchpad.llm import service as llm_service


@pytest.fixture(autouse=True)
def _restore(monkeypatch: pytest.MonkeyPatch) -> None:
    """install_fake() mutates global settings and the shared LLM service: undo after."""
    s = get_settings()
    for attr in ("llm_provider", "llm_model", "llm_fast_model", "embedding_provider",
                 "embedding_model", "gemini_api_key"):  # fmt: skip
        monkeypatch.setattr(s, attr, getattr(s, attr))
    monkeypatch.setattr(llm_service.llm, "_client_factory", llm_service.llm._client_factory)
    yield
    set_search_provider(None)


def _args(tmp_path: Path, **kw: object) -> argparse.Namespace:
    base = dict(fake=True, smoke=True, provider=None, model=None, fast_model=None, only=None,
                out=str(tmp_path), suite="all", fake_quota_calls=None)  # fmt: skip
    return argparse.Namespace(**{**base, **kw})


def _report(md_path: Path) -> dict[str, object]:
    data: dict[str, object] = json.loads(md_path.with_suffix(".json").read_text(encoding="utf-8"))
    return data


async def test_smoke_runs_three_kadak_briefs_only(tmp_path: Path) -> None:
    from evals.run import main_async

    md = await main_async(_args(tmp_path))
    data = _report(md)
    results = data["results"]
    assert isinstance(results, list)
    assert [r["id"] for r in results] == [
        "kadak-ig-monsoon",
        "kadak-carousel-fits",
        "kadak-email-early",
    ]
    assert all(r["ok"] for r in results) and data["agent"] == []
    assert md.name.startswith("fake-smoke-")
    assert "## Final texts" in md.read_text(encoding="utf-8")


async def test_quota_exhaustion_stops_cleanly_and_saves_partial_results(tmp_path: Path) -> None:
    from evals.run import main_async

    # Brief 1 takes 9-10 model calls (write, review rounds, the eval's final re-score); a
    # 12-call quota lets it finish and runs out during brief 2.
    md = await main_async(_args(tmp_path, fake_quota_calls=12))
    data = _report(md)
    meta = data["meta"]
    assert isinstance(meta, dict)
    partial = meta["partial"]
    assert partial["at"] == "kadak-carousel-fits"
    assert partial["skipped"] == ["kadak-email-early"]
    assert "per day" in partial["reason"]
    results = data["results"]
    assert isinstance(results, list)
    assert [r["id"] for r in results] == ["kadak-ig-monsoon"]  # completed work is kept
    assert "PARTIAL RUN" in md.read_text(encoding="utf-8")

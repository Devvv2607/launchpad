from __future__ import annotations

from pathlib import Path

import pytest

from launchpad.config import Settings


def test_fresh_env_example_loads(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A verbatim copy of .env.example (blank providers) must load, not crash."""
    example = Path(__file__).resolve().parents[2] / ".env.example"
    (tmp_path / ".env").write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    for var in ("LLM_PROVIDER", "EMBEDDING_PROVIDER", "IMAGE_PROVIDER", "LLM_MODEL"):
        monkeypatch.delenv(var, raising=False)
    s = Settings(_env_file=(tmp_path / ".env",))  # type: ignore[call-arg]
    assert s.llm_provider is None
    assert s.embedding_provider is None
    assert s.image_provider is None
    assert s.llm_model is None


def test_cors_origins_accepts_comma_list(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "https://a.example, https://b.example")
    assert Settings().cors_origins == ["https://a.example", "https://b.example"]

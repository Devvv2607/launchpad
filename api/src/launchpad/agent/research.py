"""Web research behind an interface (Tavily by default). Results always carry source URLs;
when research isn't configured the tool says so instead of inventing trends."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import httpx

from launchpad.config import get_settings
from launchpad.llm.http import map_status


class ResearchNotConfigured(Exception):
    pass


@dataclass(frozen=True)
class Source:
    title: str
    url: str
    snippet: str
    published: str | None = None


class SearchProvider(Protocol):
    async def search(
        self, query: str, *, max_results: int = 5, recent: bool = True
    ) -> list[Source]: ...


class TavilySearch:
    URL = "https://api.tavily.com/search"

    def __init__(self, api_key: str, http: httpx.AsyncClient | None = None) -> None:
        self._key = api_key
        self._http = http or httpx.AsyncClient(timeout=httpx.Timeout(20.0))

    async def search(
        self, query: str, *, max_results: int = 5, recent: bool = True
    ) -> list[Source]:
        body: dict[str, object] = {
            "query": query,
            "topic": "general",
            "search_depth": "basic",
            "max_results": max_results,
            "country": "india",
        }
        if recent:
            body["time_range"] = "month"
        resp = await self._http.post(
            self.URL, json=body, headers={"authorization": f"Bearer {self._key}"}
        )
        if resp.status_code >= 400:
            try:
                payload: object = resp.json()
            except ValueError:
                payload = {"error": resp.text[:200]}
            raise map_status(
                provider="tavily", model="search", status=resp.status_code, body=payload,
                headers=resp.headers, request_id=resp.headers.get("x-request-id"),
                model_env_var="TAVILY_API_KEY",
            )  # fmt: skip
        return [
            Source(
                title=str(r.get("title") or r.get("url")),
                url=str(r["url"]),
                snippet=str(r.get("content") or "")[:500],
                published=r.get("published_date"),
            )
            for r in resp.json().get("results", [])
            if r.get("url")
        ]


_provider: SearchProvider | None = None


def get_search() -> SearchProvider:
    if _provider is not None:
        return _provider
    key = get_settings().tavily_api_key
    if key is None or not key.get_secret_value():
        raise ResearchNotConfigured(
            "Web research isn't configured. Set TAVILY_API_KEY in .env to enable trend research."
        )
    return TavilySearch(key.get_secret_value())


def set_search_provider(provider: SearchProvider | None) -> None:
    """Test hook."""
    global _provider
    _provider = provider

"""Web research behind an interface (Tavily by default). Results always carry source URLs;
when research isn't configured the tool says so instead of inventing trends."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
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


# Social and video platforms aren't citable trend sources (and are mostly login-walled).
EXCLUDED_DOMAINS = [
    "facebook.com", "instagram.com", "x.com", "twitter.com", "linkedin.com", "youtube.com",
    "pinterest.com", "reddit.com", "tiktok.com", "threads.net", "quora.com",
]  # fmt: skip


def build_query(query: str, *, brand: str, category: str, city: str | None, today: date) -> str:
    """The agent's query, anchored to the brand, its category, its city and this month."""
    q = query.strip()
    extras = [brand, category, city or "India", today.strftime("%B %Y")]
    return " ".join([q, *(e for e in extras if e and e.lower() not in q.lower())])


def usable(url: str, score: float | None, min_score: float) -> bool:
    path = url.lower().split("?", 1)[0]
    if path.endswith(".pdf"):
        return False
    host = path.split("//", 1)[-1].split("/", 1)[0]
    if any(host == d or host.endswith("." + d) for d in EXCLUDED_DOMAINS):
        return False
    return score is None or score >= min_score


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
            "max_results": max_results * 2,  # room for the filters below
            "country": "india",
            "exclude_domains": EXCLUDED_DOMAINS,
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
        min_score = get_settings().research_min_score
        return [
            Source(
                title=str(r.get("title") or r.get("url")),
                url=str(r["url"]),
                snippet=str(r.get("content") or "")[:500],
                published=r.get("published_date"),
            )
            for r in resp.json().get("results", [])
            if r.get("url") and usable(str(r["url"]), r.get("score"), min_score)
        ][:max_results]


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

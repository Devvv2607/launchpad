"""Fetch a brand's homepage + up to N same-domain pages, politely and safely.

Safety: user-supplied URLs are fetched by our server, so every hop (including redirects)
is resolved and rejected if it points at a private/loopback/link-local/reserved address
(SSRF). Politeness: robots.txt is honoured, pages are fetched sequentially with a small
delay, and each response is capped in size.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from dataclasses import dataclass, field
from urllib.parse import urldefrag, urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from launchpad.rag.extract import Section, from_html

USER_AGENT = "LaunchpadBot/0.1 (+brand knowledge import)"
MAX_PAGE_BYTES = 2 * 1024 * 1024
MAX_REDIRECTS = 5
SKIP_EXT = (
    ".pdf",
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".svg",
    ".zip",
    ".mp4",
    ".css",
    ".js",
    ".xml",
)


class CrawlError(Exception):
    pass


@dataclass
class CrawlResult:
    sections: list[Section] = field(default_factory=list)
    pages: list[str] = field(default_factory=list)
    skipped: dict[str, str] = field(default_factory=dict)  # url -> reason
    title: str | None = None


def _is_public_ip(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    return not (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_reserved
        or addr.is_unspecified
    )


async def _resolve(host: str, port: int) -> set[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, port)
    return {str(info[4][0]) for info in infos}


async def assert_public_url(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise CrawlError("Only public http(s) URLs can be imported.")
    try:
        ips = await _resolve(parts.hostname, parts.port or 443)
    except socket.gaierror as exc:
        raise CrawlError(f"Couldn't resolve {parts.hostname}.") from exc
    if not ips or not all(_is_public_ip(ip) for ip in ips):
        raise CrawlError("That address points to a private or local network and can't be imported.")


async def _get(client: httpx.AsyncClient, url: str) -> tuple[str, httpx.Response]:
    """GET with manual redirects so each hop is SSRF-checked. Returns (final_url, response)."""
    for _ in range(MAX_REDIRECTS + 1):
        await assert_public_url(url)
        async with client.stream("GET", url) as resp:
            if resp.is_redirect:
                location = resp.headers.get("location")
                if not location:
                    raise CrawlError("Redirect without a location.")
                url = urljoin(url, location)
                continue
            body = bytearray()
            async for chunk in resp.aiter_bytes():
                body.extend(chunk)
                if len(body) > MAX_PAGE_BYTES:
                    raise CrawlError("Page is larger than 2 MB.")
            return url, httpx.Response(
                resp.status_code, headers=resp.headers, content=bytes(body), request=resp.request
            )
    raise CrawlError("Too many redirects.")


async def _robots(client: httpx.AsyncClient, base: str) -> RobotFileParser:
    rp = RobotFileParser()
    try:
        _, resp = await _get(client, urljoin(base, "/robots.txt"))
        rp.parse(resp.text.splitlines() if resp.status_code == 200 else [])
    except (CrawlError, httpx.HTTPError):
        rp.parse([])  # unreachable robots.txt: treat as allow-all, like major crawlers
    return rp


def _same_site(a: str, b: str) -> bool:
    ha, hb = urlsplit(a).hostname or "", urlsplit(b).hostname or ""
    return ha.removeprefix("www.") == hb.removeprefix("www.")


async def crawl(
    start_url: str,
    *,
    max_pages: int = 10,
    delay_s: float = 0.5,
    transport: httpx.AsyncBaseTransport | None = None,
) -> CrawlResult:
    result = CrawlResult()
    async with httpx.AsyncClient(
        headers={"user-agent": USER_AGENT, "accept": "text/html,application/xhtml+xml"},
        timeout=httpx.Timeout(15.0),
        follow_redirects=False,
        transport=transport,
    ) as client:
        robots = await _robots(client, start_url)
        queue: list[str] = [start_url]
        seen: set[str] = set()
        while queue and len(result.pages) < max_pages:
            url = urldefrag(queue.pop(0))[0]
            key = url.rstrip("/")  # dedupe "/x" and "/x/"; fetch the URL as written
            if key in seen:
                continue
            seen.add(key)
            if not robots.can_fetch(USER_AGENT, url):
                result.skipped[url] = "disallowed by robots.txt"
                continue
            try:
                final, resp = await _get(client, url)
            except (CrawlError, httpx.HTTPError) as exc:
                if not result.pages and key == start_url.rstrip("/"):
                    raise CrawlError(f"Couldn't fetch {url}: {exc}") from exc
                result.skipped[url] = str(exc)
                continue
            ctype = resp.headers.get("content-type", "")
            if resp.status_code != 200 or "html" not in ctype:
                result.skipped[url] = f"HTTP {resp.status_code} {ctype.split(';')[0]}"
                if not result.pages and key == start_url.rstrip("/"):
                    raise CrawlError(f"{url} returned HTTP {resp.status_code}.")
                continue
            sections, links, title = from_html(resp.text, final)
            result.title = result.title or title
            result.pages.append(final)
            result.sections.extend(sections)
            for href in links:
                nxt = urldefrag(urljoin(final, href))[0]
                if (
                    _same_site(nxt, start_url)
                    and urlsplit(nxt).scheme in ("http", "https")
                    and not nxt.lower().endswith(SKIP_EXT)
                    and nxt.rstrip("/") not in seen
                ):
                    queue.append(nxt)
            if delay_s:
                await asyncio.sleep(delay_s)
    if not result.sections:
        raise CrawlError("No readable text found on that site.")
    return result

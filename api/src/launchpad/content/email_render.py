"""Render structured email content to responsive, sanitised HTML + a plain-text alternative.

Safety is layered: every LLM- or user-supplied value is autoescaped by Jinja, links are
restricted to http(s)/mailto, and the final HTML is passed through an allow-list sanitiser.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html import escape as html_escape
from pathlib import Path
from urllib.parse import urlsplit

import nh3
from jinja2 import Environment, FileSystemLoader, select_autoescape

from launchpad.content.schemas import EmailContent
from launchpad.services.colors import contrast_ratio, hex_to_rgb

_env = Environment(
    loader=FileSystemLoader(str(Path(__file__).parent / "templates")),
    autoescape=select_autoescape(["html", "j2"]),
)

ALLOWED_TAGS = {
    "div", "span", "table", "tr", "td", "p", "h1", "h2", "ul", "li",
    "a", "img", "br", "strong", "em",
}  # fmt: skip
# Static document shell (no user data) — the sanitiser works on fragments and would drop it.
SKELETON = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="x-apple-disable-message-reformatting">
<title>{title}</title>
</head>
<body style="margin:0;padding:0;background:#f4f5f8;">
{body}
</body>
</html>
"""
ALLOWED_ATTRS = {
    "*": {"style", "align", "role"},
    "a": {"href"},
    "img": {"src", "alt", "height", "width"},
    "table": {"width", "cellpadding", "cellspacing", "border", "bgcolor"},
    "td": {"bgcolor", "width"},
}
DEFAULT_PRIMARY = "#1E2250"
DEFAULT_SECONDARY = "#F0A020"
_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


@dataclass(frozen=True)
class RenderedEmail:
    subject: str
    preheader: str
    html: str
    text: str


def safe_url(url: str | None, fallback: str) -> str:
    candidate = (url or "").strip()
    parts = urlsplit(candidate)
    if parts.scheme in ("http", "https") and parts.netloc:
        return candidate
    if parts.scheme == "mailto":
        return candidate
    return fallback


def render_email(
    content: EmailContent,
    *,
    subject_index: int = 0,
    business_name: str,
    website: str | None,
    locations: list[str],
    primary_color: str | None,
    secondary_color: str | None,
    logo_url: str | None,
    unsubscribe_url: str = "{{unsubscribe_url}}",
) -> RenderedEmail:
    primary = primary_color if primary_color and _HEX.match(primary_color) else DEFAULT_PRIMARY
    secondary = (
        secondary_color if secondary_color and _HEX.match(secondary_color) else DEFAULT_SECONDARY
    )
    button_text = (
        "#FFFFFF"
        if contrast_ratio(hex_to_rgb(primary), (255, 255, 255))
        >= contrast_ratio(hex_to_rgb(primary), (0, 0, 0))
        else "#000000"
    )
    fallback_url = safe_url(website, "#")
    sections = []
    for s in content.sections:
        data = s.model_dump()
        if s.type == "cta":
            data["button_url"] = safe_url(s.button_url, fallback_url)
            data["button_label"] = s.button_label or "Learn more"
        sections.append(data)
    subject = content.subject_variants[subject_index]
    fragment = _env.get_template("email.html.j2").render(
        preheader=content.preheader,
        sections=sections,
        business_name=business_name,
        locations=", ".join(locations),
        primary=primary,
        secondary=secondary,
        button_text=button_text,
        logo_url=logo_url if logo_url and urlsplit(logo_url).scheme in ("http", "https") else None,
        unsubscribe_url=unsubscribe_url,
    )
    clean = nh3.clean(
        fragment,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRS,
        url_schemes={"http", "https", "mailto"},
        strip_comments=True,
        link_rel=None,
    )
    html = SKELETON.format(title=html_escape(subject), body=clean)
    return RenderedEmail(subject, content.preheader, html, plain_text(content, website))


def plain_text(content: EmailContent, website: str | None) -> str:
    lines: list[str] = []
    for s in content.sections:
        if s.heading:
            lines += [s.heading.upper() if s.type == "hero" else s.heading, ""]
        if s.body:
            lines += [s.body, ""]
        lines += [f"- {item}" for item in s.items]
        if s.items:
            lines.append("")
        if s.type == "cta":
            lines += [
                f"{s.button_label or 'Learn more'}: {safe_url(s.button_url, website or '')}",
                "",
            ]
    return "\n".join(lines).strip() + "\n"

"""Versioned prompt templates.

Each `*.md.j2` file starts with a front-matter block:

    ---
    name: write_content
    version: 2026-10-02.1
    ---

followed by `<<<system>>>` and `<<<user>>>` sections (Jinja2, StrictUndefined). The version
string is stored on every llm_calls row, so a quality change can be traced to a prompt edit.
Bump the version whenever the text changes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from jinja2 import Environment, StrictUndefined

_DIR = Path(__file__).parent
_FRONT = re.compile(r"\A---\n(.*?)\n---\n", re.S)
_SECTION = re.compile(r"^<<<(system|user)>>>\s*$", re.M)
# Prompts are plain text sent to an LLM, never rendered as HTML, so autoescaping is off.
_env = Environment(
    undefined=StrictUndefined,
    autoescape=False,  # noqa: S701
    trim_blocks=True,
    lstrip_blocks=True,
)


@dataclass(frozen=True)
class RenderedPrompt:
    name: str
    version: str
    system: str
    user: str


@dataclass(frozen=True)
class Prompt:
    name: str
    version: str
    system_template: str
    user_template: str

    def render(self, **ctx: Any) -> RenderedPrompt:
        return RenderedPrompt(
            name=self.name,
            version=self.version,
            system=_env.from_string(self.system_template).render(**ctx).strip(),
            user=_env.from_string(self.user_template).render(**ctx).strip(),
        )


@lru_cache
def load_prompt(name: str) -> Prompt:
    path = _DIR / f"{name}.md.j2"
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    front = _FRONT.match(text)
    if not front:
        raise ValueError(f"{path.name}: missing front matter")
    meta = dict(line.split(":", 1) for line in front.group(1).splitlines() if ":" in line)
    meta = {k.strip(): v.strip() for k, v in meta.items()}
    body = text[front.end() :]
    parts = _SECTION.split(body)
    # parts: [preamble, 'system', text, 'user', text]
    sections = {parts[i]: parts[i + 1] for i in range(1, len(parts) - 1, 2)}
    if meta.get("name") != name or not meta.get("version"):
        raise ValueError(f"{path.name}: front matter needs matching 'name' and a 'version'")
    if "system" not in sections or "user" not in sections:
        raise ValueError(f"{path.name}: needs <<<system>>> and <<<user>>> sections")
    return Prompt(name, meta["version"], sections["system"], sections["user"])


def all_prompts() -> list[Prompt]:
    return [load_prompt(p.name.removesuffix(".md.j2")) for p in sorted(_DIR.glob("*.md.j2"))]

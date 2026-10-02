"""Heading-aware chunking with overlap.

Token counts use a ~4 chars/token estimate (good enough for sizing; embedding models have
their own tokenizers). Chunks never straddle two headings, so every chunk's citation is
accurate; the heading is prefixed to the chunk text to give the embedding context.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from launchpad.rag.extract import Section

TARGET_TOKENS = 650  # within the 500-800 band
MAX_TOKENS = 800
MIN_TOKENS = 500
OVERLAP_TOKENS = 80
CHARS_PER_TOKEN = 4

_SENTENCE = re.compile(r"(?<=[.!?])\s+")


def est_tokens(text: str) -> int:
    return max(1, len(text) // CHARS_PER_TOKEN)


@dataclass
class Chunk:
    text: str
    heading: str | None
    page: int | None
    source: str
    tokens: int


def _units(text: str) -> list[str]:
    """Paragraphs, further split into sentences when a paragraph alone is too big."""
    units: list[str] = []
    for para in re.split(r"\n\s*\n|\n", text):
        para = para.strip()
        if not para:
            continue
        if est_tokens(para) <= MAX_TOKENS:
            units.append(para)
            continue
        for sentence in _SENTENCE.split(para):
            while est_tokens(sentence) > MAX_TOKENS:  # pathological run-on text
                cut = MAX_TOKENS * CHARS_PER_TOKEN
                units.append(sentence[:cut])
                sentence = sentence[cut:]
            if sentence.strip():
                units.append(sentence.strip())
    return units


def chunk_sections(sections: list[Section]) -> list[Chunk]:
    chunks: list[Chunk] = []
    for section in sections:
        units = _units(section.text)
        current: list[str] = []

        for unit in units:
            size = est_tokens("\n".join(current))
            if current and size + est_tokens(unit) > TARGET_TOKENS and size >= MIN_TOKENS // 2:
                _emit(chunks, section, current)
                # Overlap: carry the tail of the previous chunk into the next one.
                tail: list[str] = []
                for prev in reversed(current):
                    if est_tokens("\n".join([prev, *tail])) > OVERLAP_TOKENS:
                        break
                    tail.insert(0, prev)
                current = tail
            current.append(unit)
        _emit(chunks, section, current)
    return _merge_tiny(chunks)


def _emit(chunks: list[Chunk], section: Section, current: list[str]) -> None:
    body = "\n".join(current).strip()
    if body:
        text = f"{section.heading}\n{body}" if section.heading else body
        chunks.append(Chunk(text, section.heading, section.page, section.source, est_tokens(text)))


def _merge_tiny(chunks: list[Chunk]) -> list[Chunk]:
    """Fold very small chunks into a neighbour from the same heading/page."""
    out: list[Chunk] = []
    for c in chunks:
        prev = out[-1] if out else None
        if (
            prev is not None
            and c.tokens < 60
            and prev.heading == c.heading
            and prev.page == c.page
            and prev.tokens + c.tokens <= MAX_TOKENS
        ):
            prev.text += "\n" + c.text.removeprefix(f"{c.heading}\n" if c.heading else "")
            prev.tokens = est_tokens(prev.text)
        else:
            out.append(c)
    return out

"""Concrete facts in marketing copy (prices, percentages, dates, durations, quantities, numbers),
extracted deterministically so they can be checked against their sources.

Used after generation:
- grounding: every fact in a draft must be supported by the brief, brand kit, retrieved brand
  documents or campaign plan item (an invented "4 designs" or a wrong date fails);
- spec-dumping: too many product facts in one caption;
- variant overlap: two variants built from the same facts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

_HYPHENS = re.compile("[‐-―−]")  # typographic hyphens/dashes -> "-"
_MONTHS = {
    m: i + 1
    for i, names in enumerate(
        [("jan", "january"), ("feb", "february"), ("mar", "march"), ("apr", "april"),
         ("may",), ("jun", "june"), ("jul", "july"), ("aug", "august"),
         ("sep", "sept", "september"), ("oct", "october"), ("nov", "november"),
         ("dec", "december")]
    )
    for m in names
}  # fmt: skip
_MONTH = (
    r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?"
    r"|sept?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
)
_ORD = r"(?:st|nd|rd|th)?"

# Countable things a caption might quantify. Grouped so "5 tees" and "5 designs" compare.
UNIT_GROUPS: dict[str, tuple[str, ...]] = {
    "item": ("tee", "tees", "t-shirt", "t-shirts", "tshirt", "tshirts", "shirt", "shirts",
             "design", "designs", "graphic", "graphics", "piece", "pieces", "style", "styles",
             "print", "prints", "product", "products", "item", "items", "drop", "drops"),
    "colour": ("colour", "colours", "color", "colors", "shade", "shades"),
    "size": ("size", "sizes"),
    "person": ("people", "person", "customers", "members", "fans", "followers"),
}  # fmt: skip
_UNIT_OF = {w: g for g, words in UNIT_GROUPS.items() for w in words}
_DURATION = {"min": "min", "mins": "min", "minute": "min", "minutes": "min", "hr": "h",
             "hrs": "h", "hour": "h", "hours": "h", "day": "d", "days": "d", "week": "w",
             "weeks": "w", "month": "mo", "months": "mo", "year": "y", "years": "y"}  # fmt: skip
_MEASURE = {"gsm": "gsm", "kg": "kg", "g": "g", "gm": "g", "ml": "ml", "l": "l", "cm": "cm",
            "mm": "mm", "km": "km", "inch": "in", "inches": "in"}  # fmt: skip

PRICE = re.compile(r"(?:₹|\brs\.?|\binr)\s?(\d+(?:,\d+)*(?:\.\d+)?)", re.I)
PERCENT = re.compile(r"(\d+(?:\.\d+)?)\s?(?:%|percent\b|per cent\b)", re.I)
ISO_DATE = re.compile(r"\b(20\d\d)-(\d\d)-(\d\d)\b")
DAY_MONTH = re.compile(rf"\b(\d{{1,2}}){_ORD}\s+(?:of\s+)?{_MONTH}\b\.?", re.I)
MONTH_DAY = re.compile(rf"\b{_MONTH}\.?\s+(\d{{1,2}}){_ORD}\b", re.I)
RANGE = re.compile(r"\b(\d+)\s?(?:-|to|–)\s?(\d+)\b(?:\s+([a-z-]+))?", re.I)
NUM_UNIT = re.compile(r"\b(\d+)\s?-?\s?([a-z][a-z-]*)\b((?:\s+[a-z][a-z-]*){0,2})", re.I)
BARE = re.compile(r"(?<![\w#@₹.,])(\d+(?:,\d{3})*)(?![\w%])")
_IGNORE = re.compile(r"[#@][\w-]+|https?://\S+|\b\d{1,2}(?::\d\d)?\s?(?:am|pm)\b", re.I)


@dataclass(frozen=True)
class Fact:
    kind: str  # price | percent | date | duration | measure | quantity | number | range
    key: str  # normalised, comparable form, e.g. "price:699", "quantity:item:5", "date:10-12"
    text: str  # as written

    @property
    def number(self) -> str:
        return self.key.rsplit(":", 1)[-1]


def _clean(text: str) -> str:
    return _IGNORE.sub(" ", _HYPHENS.sub("-", text))


def extract_facts(text: str) -> list[Fact]:
    s = _clean(text)
    facts: list[Fact] = []
    taken: list[tuple[int, int]] = []

    def free(a: int, b: int) -> bool:
        return all(b <= x or a >= y for x, y in taken)

    def add(m: re.Match[str], kind: str, key: str) -> None:
        taken.append(m.span())
        facts.append(Fact(kind, key, m.group(0).strip()))

    for m in PRICE.finditer(s):
        add(m, "price", f"price:{m.group(1).replace(',', '')}")
    for m in PERCENT.finditer(s):
        if free(*m.span()):
            add(m, "percent", f"percent:{m.group(1)}")
    for m in ISO_DATE.finditer(s):
        if free(*m.span()):
            add(m, "date", f"date:{int(m.group(2))}-{int(m.group(3))}")
    for m in DAY_MONTH.finditer(s):
        if free(*m.span()):
            add(m, "date", f"date:{_MONTHS[m.group(2).lower()]}-{int(m.group(1))}")
    for m in MONTH_DAY.finditer(s):
        if free(*m.span()):
            add(m, "date", f"date:{_MONTHS[m.group(1).lower()]}-{int(m.group(2))}")
    for m in RANGE.finditer(s):
        if free(*m.span()):
            unit = _UNIT_OF.get((m.group(3) or "").lower(), "")
            add(m, "range", f"range:{unit}:{m.group(1)}-{m.group(2)}")
    for m in NUM_UNIT.finditer(s):
        if not free(*m.span(1)):
            continue
        n, word = m.group(1), m.group(2).lower()
        if word in _DURATION:
            add(m, "duration", f"duration:{n}{_DURATION[word]}")
        elif word in _MEASURE:
            add(m, "measure", f"measure:{n}{_MEASURE[word]}")
        else:
            # "5 rain-themed graphic tees": the unit may follow up to two describing words.
            words = [word, *(w.lower() for w in (m.group(3) or "").split())]
            group = next((_UNIT_OF[w] for w in words if w in _UNIT_OF), None)
            if group:
                add(m, "quantity", f"quantity:{group}:{n}")
    for m in BARE.finditer(s):
        if free(*m.span()):
            add(m, "number", f"number:{m.group(1).replace(',', '')}")
    return facts


def date_fact(d: date) -> Fact:
    return Fact("date", f"date:{d.month}-{d.day}", d.isoformat())


def is_supported(fact: Fact, sources: list[Fact]) -> bool:
    """A fact is supported when the sources state it. Quantities and bare numbers may be backed
    by the same number with a compatible unit or none; a number that only appears as one end of a
    range ("drops of 4 to 6 tees") doesn't support a specific claim ("4 designs")."""
    keys = {f.key for f in sources}
    if fact.key in keys:
        return True
    if fact.kind not in ("quantity", "number"):
        return False
    n = fact.number
    if fact.kind == "quantity":  # "5 tees" is backed by "5 tees"/"5 designs" or a bare 5
        unit = fact.key.split(":")[1]
        return any(
            (f.kind == "quantity" and f.key.split(":")[1] == unit and f.number == n)
            or (f.kind == "number" and f.number == n)
            for f in sources
        )
    # A bare number in the output is backed by the same number stated anywhere (not in a range).
    return any(
        f.kind != "range" and f.number.rstrip("abcdefghijklmnopqrstuvwxyz") == n for f in sources
    )


def unsupported(output: str, sources: list[Fact]) -> list[Fact]:
    seen: set[str] = set()
    out = []
    for f in extract_facts(output):
        if f.kind == "range" or f.key in seen:
            continue
        seen.add(f.key)
        if not is_supported(f, sources):
            out.append(f)
    return out

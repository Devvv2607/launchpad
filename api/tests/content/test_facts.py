from __future__ import annotations

from datetime import date

from launchpad.content.facts import date_fact, extract_facts, unsupported

KADAK_DOC = (
    "Kadak Tees is a Mumbai streetwear label started in 2022. Graphic tees: 100% combed cotton, "
    "220 GSM, sizes XS to XXL. Price: ₹699 per tee for drops; bundles of 3 for ₹1,899. Free "
    "shipping on orders above ₹999; cash on delivery available. Orders ship within 48 hours. "
    "Easy 7-day size exchange. We release designs in themed drops of 4 to 6 tees, announced 3 "
    "days ahead. Each design is printed in a limited batch of 150."
)
BRIEF = "Monsoon drop: 5 rain‑themed graphic tees, ₹699 each"


def _keys(text: str) -> set[str]:
    return {f.key for f in extract_facts(text)}


def test_extracts_each_kind_of_fact() -> None:
    keys = _keys(
        "5 rain‑themed graphic tees at ₹699, 3 for Rs. 1,899, 15% off, 220 GSM, ships in 48 hrs, "
        "7‑day exchange, live from Oct 12, batch of 150, #Top10 at 2am"
    )
    assert {"quantity:item:5", "price:699", "price:1899", "percent:15", "measure:220gsm",
            "duration:48h", "duration:7d", "date:10-12", "number:150"} <= keys  # fmt: skip
    assert "number:10" not in keys  # hashtags and times are not facts
    assert _keys("12th October and 2026-10-10") == {"date:10-12", "date:10-10"}


def test_invented_design_count_is_caught_even_with_a_range_in_the_brand_doc() -> None:
    sources = extract_facts(BRIEF + " " + KADAK_DOC)
    bad = unsupported("Grab any of the 4 designs – ₹699 each, 220 GSM.", sources)
    assert [f.text for f in bad] == ["4 designs"]


def test_campaign_date_mismatch_is_caught() -> None:
    sources = [*extract_facts(KADAK_DOC), date_fact(date(2026, 10, 10))]
    assert [f.key for f in unsupported("The drop is live from Oct 12.", sources)] == ["date:10-12"]
    assert unsupported("The drop is live from 10 Oct.", sources) == []


def test_grounded_caption_passes_and_derived_prices_do_not() -> None:
    sources = extract_facts(BRIEF + " " + KADAK_DOC)
    good = (
        "5 rain‑themed tees, ₹699 each or 3 for ₹1,899. 100% combed cotton, 220 GSM. "
        "Limited batch of 150, ships within 48 hrs, 7‑day size exchange."
    )
    assert unsupported(good, sources) == []
    assert [f.key for f in unsupported("That's ₹633 a tee!", sources)] == ["price:633"]

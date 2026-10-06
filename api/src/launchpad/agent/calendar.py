"""Indian festivals and observances, Oct 2026 - Oct 2027, for campaign planning.

Sources (checked 2026-10-06):
  GOI-2027  DoPT O.M. No. 12/2/2023-JCA (16 Jul 2026), gazetted holidays 2027
            (reported at staffnews.in / gconnect.in)
  GOI-2026  Gazetted holidays 2026 (Diwali, Guru Nanak's Birthday, Christmas)
  PANCHANG  Agreement across drikpanchang.com / hindupad.com / hindutone.com calendars
  FIXED     Fixed-date observances

Islamic festival dates depend on moon sighting and can move by a day; they're flagged.
Dates where sources disagreed (e.g. Bhai Dooj 2026, Govardhan Puja 2026) are left out
rather than guessed — add them once confirmed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Observance:
    day: date
    name: str
    kind: str  # festival | national | commercial | awareness
    regions: str  # "All India" or the states/communities where it's big
    note: str = ""
    source: str = "PANCHANG"
    moon_dependent: bool = False


_D = date
CALENDAR: tuple[Observance, ...] = (
    Observance(_D(2026, 10, 11), "Navratri begins", "festival", "All India; big in Gujarat, Maharashtra, Bengal (Durga Puja)"),
    Observance(_D(2026, 10, 20), "Dussehra (Vijayadashami)", "festival", "All India", "Durga Puja culminates in Bengal"),
    Observance(_D(2026, 10, 29), "Karwa Chauth", "festival", "North India (Punjab, Haryana, UP, Delhi, Rajasthan)"),
    Observance(_D(2026, 11, 6), "Dhanteras", "commercial", "All India", "Biggest buying day for gold, utensils, electronics"),
    Observance(_D(2026, 11, 8), "Diwali (Deepavali)", "festival", "All India", "Gifting season peaks the week before", "GOI-2026"),
    Observance(_D(2026, 11, 14), "Children's Day", "awareness", "All India", source="FIXED"),
    Observance(_D(2026, 11, 15), "Chhath Puja", "festival", "Bihar, Jharkhand, eastern UP; diaspora in Mumbai and Delhi"),
    Observance(_D(2026, 11, 24), "Guru Nanak Jayanti (Gurpurab)", "festival", "All India; big in Punjab", source="GOI-2026"),
    Observance(_D(2026, 11, 27), "Black Friday sales", "commercial", "Online retail", "Day after US Thanksgiving; Indian e-commerce runs sales", "FIXED"),
    Observance(_D(2026, 12, 25), "Christmas", "festival", "All India; big in Goa, Kerala, Northeast, Mumbai", source="GOI-2026"),
    Observance(_D(2026, 12, 31), "New Year's Eve", "commercial", "Urban India", "Peak night for cafés, restaurants, events", "FIXED"),
    Observance(_D(2027, 1, 1), "New Year's Day", "commercial", "All India", "Resolutions: fitness and learning sign-ups peak", "FIXED"),
    Observance(_D(2027, 1, 13), "Lohri", "festival", "Punjab, Haryana, Delhi", source="FIXED"),
    Observance(_D(2027, 1, 14), "Makar Sankranti / Pongal / Uttarayan", "festival", "All India (Pongal: Tamil Nadu; Uttarayan kites: Gujarat)", "Some regions observe on 15 Jan"),
    Observance(_D(2027, 1, 26), "Republic Day", "national", "All India", source="GOI-2027"),
    Observance(_D(2027, 2, 14), "Valentine's Day", "commercial", "Urban India", source="FIXED"),
    Observance(_D(2027, 3, 10), "Eid-ul-Fitr", "festival", "All India", "End of Ramzan; date depends on moon sighting", "GOI-2027", True),
    Observance(_D(2027, 3, 22), "Holika Dahan", "festival", "North and West India", "Evening before Holi"),
    Observance(_D(2027, 3, 23), "Holi", "festival", "All India; biggest in the North", "Gazetted date (Dhulandi)", "GOI-2027"),
    Observance(_D(2027, 3, 26), "Good Friday", "festival", "All India", source="GOI-2027"),
    Observance(_D(2027, 4, 14), "Baisakhi / Ambedkar Jayanti", "festival", "Punjab (Baisakhi); All India (Ambedkar Jayanti)", source="FIXED"),
    Observance(_D(2027, 4, 15), "Ram Navami", "festival", "All India", source="GOI-2027"),
    Observance(_D(2027, 4, 19), "Mahavir Jayanti", "festival", "All India; Jain community", source="GOI-2027"),
    Observance(_D(2027, 5, 9), "Mother's Day", "commercial", "Urban India", "Second Sunday of May", "FIXED"),
    Observance(_D(2027, 5, 17), "Eid-ul-Zuha (Bakrid)", "festival", "All India", "Date depends on moon sighting", "GOI-2027", True),
    Observance(_D(2027, 5, 20), "Buddha Purnima", "festival", "All India", source="GOI-2027"),
    Observance(_D(2027, 6, 16), "Muharram", "festival", "All India", "Date depends on moon sighting", "GOI-2027", True),
    Observance(_D(2027, 6, 20), "Father's Day", "commercial", "Urban India", "Third Sunday of June", "FIXED"),
    Observance(_D(2027, 6, 21), "International Yoga Day", "awareness", "All India", "Natural fit for fitness and wellness brands", "FIXED"),
    Observance(_D(2027, 8, 15), "Independence Day", "national", "All India", "Also Id-e-Milad in 2027 (moon-dependent)", "GOI-2027"),
    Observance(_D(2027, 8, 17), "Raksha Bandhan", "festival", "All India; biggest in the North and West", "Gifting for siblings"),
    Observance(_D(2027, 8, 25), "Janmashtami", "festival", "All India; Dahi Handi in Maharashtra", source="GOI-2027"),
    Observance(_D(2027, 9, 4), "Ganesh Chaturthi", "festival", "Maharashtra, Karnataka, Goa, Telangana", "10-day festival; Mumbai's biggest"),
    Observance(_D(2027, 9, 5), "Teachers' Day", "awareness", "All India", source="FIXED"),
    Observance(_D(2027, 10, 2), "Gandhi Jayanti", "national", "All India", source="GOI-2027"),
    Observance(_D(2027, 10, 9), "Dussehra (Vijayadashami)", "festival", "All India", source="GOI-2027"),
    Observance(_D(2027, 10, 29), "Diwali (Deepavali)", "festival", "All India", source="GOI-2027"),
)  # fmt: skip

COVERAGE = (CALENDAR[0].day, CALENDAR[-1].day)


def between(start: date, end: date) -> list[Observance]:
    return [o for o in CALENDAR if start <= o.day <= end]


def as_dict(o: Observance) -> dict[str, str | bool]:
    return {
        "date": o.day.isoformat(),
        "weekday": o.day.strftime("%A"),
        "name": o.name,
        "kind": o.kind,
        "regions": o.regions,
        "note": o.note,
        "source": o.source,
        "moon_dependent": o.moon_dependent,
    }

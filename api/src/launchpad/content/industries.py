"""Industry knowledge used to steer content. Qualitative guidance only — no invented stats.

Posting windows are general starting points in the workspace's local time, labelled as
such in the UI; once real metrics exist (Phase 6) they should be replaced by the
workspace's own best-performing times.
"""

from __future__ import annotations

from dataclasses import dataclass

from launchpad.domain.enums import Industry


@dataclass(frozen=True)
class IndustryProfile:
    focus: str  # what to emphasise
    content_ideas: str  # formats that tend to work
    email_focus: str
    seed_hashtags: tuple[str, ...]  # broad tags; the hashtag service adds niche/local/branded
    posting_windows: tuple[str, ...]  # local-time starting points, not measured data
    avoid: str = ""  # compliance or tone pitfalls


INDUSTRIES: dict[Industry, IndustryProfile] = {
    Industry.FASHION: IndustryProfile(
        "style, trends, fabric quality, fit, seasonal collections",
        "styling tips, outfit inspiration, fabric close-ups, try-on reels, festive edits",
        "new collections, styling guides, exclusive offers, seasonal trends",
        ("#fashion", "#style", "#ootd", "#fashionista", "#ethnicwear"),
        ("Mon/Wed/Fri 12-1 PM", "Weekdays 7-9 PM"),
    ),
    Industry.FOOD: IndustryProfile(
        "taste, fresh ingredients, the dining experience, signature dishes, offers",
        "dish close-ups, behind-the-counter prep, regulars' stories, seasonal menus",
        "menu highlights, special offers, events, recipes and tips",
        ("#food", "#foodie", "#cafe", "#instafood", "#foodlover"),
        ("Weekdays 11 AM-1 PM", "Weekdays 5-7 PM", "Weekends 12-2 PM"),
        "Don't make health claims about food without evidence.",
    ),
    Industry.TECH: IndustryProfile(
        "the problem solved, outcomes, ease of use, reliability, ROI",
        "feature demos, customer stories, how-tos, founder insights, changelogs",
        "product updates, tutorials, case studies, industry insights",
        ("#tech", "#saas", "#startup", "#productivity", "#innovation"),
        ("Tue-Thu 9 AM-12 PM", "Tue-Thu 2-4 PM"),
    ),
    Industry.FITNESS: IndustryProfile(
        "health benefits, consistency, community, coaching quality, results",
        "workout tips, member journeys, class schedules, form checks, challenges",
        "workout plans, nutrition tips, member stories, membership offers",
        ("#fitness", "#workout", "#gym", "#fitnessmotivation", "#healthylifestyle"),
        ("Weekdays 6-8 AM", "Weekdays 5-7 PM"),
        "Avoid body-shaming language and guaranteed-results claims.",
    ),
    Industry.BEAUTY: IndustryProfile(
        "self-care, confidence, ingredients, visible results, expertise",
        "application tutorials, ingredient spotlights, transformations, routines",
        "beauty tips, tutorials, ingredient spotlights, exclusive offers",
        ("#beauty", "#skincare", "#makeup", "#selfcare", "#glowup"),
        ("Weekdays 9-11 AM", "Weekdays 6-8 PM"),
        "No medical or guaranteed-result claims.",
    ),
    Industry.EDUCATION: IndustryProfile(
        "learning outcomes, skills, career growth, teaching quality",
        "study tips, student success stories, mini-lessons, Q&A sessions",
        "course updates, learning resources, success stories, enrolment",
        ("#education", "#learning", "#students", "#upskill", "#careergrowth"),
        ("Tue-Thu 10 AM-12 PM", "Tue-Thu 3-5 PM"),
        "Don't promise jobs or guaranteed marks.",
    ),
    Industry.FINANCE: IndustryProfile(
        "trust, security, clarity, long-term growth, expertise",
        "explainers, myth-busting, checklists, market context (no tips)",
        "market updates, financial literacy, service benefits, consultations",
        ("#finance", "#personalfinance", "#money", "#investing", "#financialliteracy"),
        ("Weekdays 8-10 AM", "Weekdays 12-1 PM"),
        "No return guarantees or personalised investment advice; follow SEBI/RBI norms.",
    ),
    Industry.REAL_ESTATE: IndustryProfile(
        "location, lifestyle, investment value, amenities, trust",
        "property walkthroughs, neighbourhood guides, buyer FAQs, market notes",
        "new listings, market reports, site-visit invitations",
        ("#realestate", "#property", "#newhome", "#homebuyers", "#realestateindia"),
        ("Weekends 10 AM-1 PM", "Weekdays 7-9 PM"),
        "Mention RERA numbers where required; no guaranteed appreciation.",
    ),
    Industry.HEALTHCARE: IndustryProfile(
        "care quality, expertise, patient comfort, prevention, access",
        "health tips, doctor intros, myth-busting, clinic updates",
        "health tips, services, appointment reminders, wellness programmes",
        ("#health", "#healthcare", "#wellness", "#doctor", "#healthylife"),
        ("Weekdays 9-11 AM", "Weekdays 6-8 PM"),
        "No diagnoses, cures or before/after medical claims.",
    ),
    Industry.TRAVEL: IndustryProfile(
        "experiences, destinations, ease of booking, value, memories",
        "destination highlights, itineraries, traveller stories, packing tips",
        "destination guides, deals, booking info, travel tips",
        ("#travel", "#wanderlust", "#travelgram", "#explore", "#incredibleindia"),
        ("Thu-Sun 11 AM-1 PM", "Weekdays 7-9 PM"),
    ),
    Industry.AUTOMOTIVE: IndustryProfile(
        "performance, reliability, safety, service quality, value",
        "feature walkarounds, maintenance tips, service offers, customer deliveries",
        "new models, service reminders, offers, maintenance tips",
        ("#cars", "#automotive", "#carservice", "#drive", "#autolovers"),
        ("Weekends 10 AM-12 PM", "Weekdays 6-8 PM"),
    ),
    Industry.HOME: IndustryProfile(
        "comfort, style, function, craftsmanship, transformation",
        "room makeovers, design tips, product details, before/after",
        "design inspiration, catalogues, home-improvement tips, seasonal offers",
        ("#homedecor", "#interiordesign", "#home", "#furniture", "#interiors"),
        ("Weekends 10 AM-1 PM", "Weekdays 7-9 PM"),
    ),
    Industry.ENTERTAINMENT: IndustryProfile(
        "the experience, atmosphere, line-up, community, FOMO",
        "event teasers, behind-the-scenes, artist intros, countdowns, recaps",
        "event announcements, early-bird tickets, line-ups, recaps",
        ("#events", "#livemusic", "#weekendvibes", "#nightlife", "#entertainment"),
        ("Thu-Sat 5-9 PM",),
    ),
    Industry.PET: IndustryProfile(
        "pet health and happiness, trusted care, love, community",
        "pet care tips, customer pets, grooming transformations, vet advice",
        "care tips, product picks, health reminders, community stories",
        ("#pets", "#dogsofinstagram", "#catsofinstagram", "#petcare", "#petlovers"),
        ("Weekdays 7-9 AM", "Weekdays 6-9 PM"),
    ),
    Industry.RETAIL: IndustryProfile(
        "product variety, value, quality, convenience, service",
        "new arrivals, product spotlights, offers, customer reviews, unboxings",
        "product showcases, sale announcements, shopping guides",
        ("#shopping", "#shoplocal", "#newarrivals", "#sale", "#shopnow"),
        ("Tue-Thu 8-10 AM", "Fri-Sun 12-2 PM"),
    ),
}


def profile_for(industry: Industry) -> IndustryProfile:
    return INDUSTRIES[industry]

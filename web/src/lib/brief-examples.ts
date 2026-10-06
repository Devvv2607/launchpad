import type { Schemas } from "@/lib/api/client";

type Industry = Schemas["Industry"];

// One-click brief starters, per industry. Deliberately free of prices and dates: those must
// come from the user, so the writer never sees an invented offer.
export const BRIEF_EXAMPLES: Record<Industry, string[]> = {
  food: [
    "New seasonal menu launch",
    "Weekend special announcement",
    "Hiring post: we need staff",
    "Thank our regulars",
  ],
  fashion: [
    "New collection drop",
    "Restock of a bestseller",
    "Styling tips for the season",
    "Behind the scenes: how a design is made",
  ],
  beauty: [
    "New service launch",
    "Festive season bookings are open",
    "Skincare tip of the week",
    "Meet our stylist",
  ],
  fitness: [
    "New batch starting soon",
    "Member transformation story (with permission)",
    "Workout tip of the week",
    "Free trial class",
  ],
  healthcare: [
    "Clinic timings update",
    "Health awareness tip",
    "New specialist joining",
    "How to book an appointment",
  ],
  education: [
    "Admissions open for a new batch",
    "Student success story (with permission)",
    "Free demo class",
    "Study tip for exam season",
  ],
  tech: [
    "New feature launch",
    "Customer story (with permission)",
    "Webinar announcement",
    "Hiring post: we're growing the team",
  ],
  finance: [
    "Tax-saving reminder before the deadline",
    "Explain a common money mistake",
    "Free consultation slots",
    "Meet the advisor",
  ],
  real_estate: [
    "New project launch",
    "Site visit weekend",
    "Neighbourhood guide",
    "Home-buying checklist",
  ],
  travel: [
    "Long-weekend getaway package",
    "Guest story (with permission)",
    "Best time to visit",
    "Early-bird bookings open",
  ],
  automotive: [
    "Monsoon car-care checkup",
    "New model arrival",
    "Service centre timings",
    "Customer delivery moment",
  ],
  home: [
    "New collection in store",
    "Festive home makeover ideas",
    "Behind the build: a finished project",
    "Design consultation slots",
  ],
  entertainment: [
    "Upcoming event announcement",
    "Line-up reveal",
    "Last few tickets left",
    "Throwback to our last event",
  ],
  pet: [
    "Grooming slots open",
    "Pet-care tip for the season",
    "Meet a happy client (with permission)",
    "Adoption drive",
  ],
  retail: [
    "New arrivals this week",
    "Festive gifting guide",
    "Store timings update",
    "Customer favourite products",
  ],
};

export const GENERIC_EXAMPLES = [
  "Announce something new",
  "Share a tip with customers",
  "Thank our customers",
  "Behind the scenes",
];

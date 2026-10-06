import type { Industry } from "@/lib/labels";

// Conversation starters for the agent. Free of invented prices and dates: the agent asks or
// works from the brand kit for those.
const SPECIFIC: Record<Industry, string> = {
  food: "Plan a 1-week campaign for a new menu item, Instagram + email",
  fashion: "Plan a 2-week Instagram campaign for our next collection drop",
  beauty: "Plan festive-season posts to fill weekday appointment slots",
  fitness: "Plan a 1-week campaign to fill our next beginners' batch",
  healthcare: "Write 3 Instagram posts with seasonal health tips for our patients",
  education: "Plan an admissions campaign for our next batch, Instagram + email",
  tech: "Plan a LinkedIn + email launch for our newest feature",
  finance: "Plan LinkedIn posts reminding clients about the tax-saving deadline",
  real_estate: "Plan a 2-week campaign for a site-visit weekend",
  travel: "Plan a campaign for our next long-weekend getaway package",
  automotive: "Plan a monsoon car-care campaign for our service centre",
  home: "Plan festive home-makeover posts for Instagram",
  entertainment: "Plan a 1-week countdown campaign for our next event",
  pet: "Plan a month of Instagram posts with seasonal pet-care tips",
  retail: "Plan a festive gifting campaign, Instagram + email",
};

export function starterPrompts(industry: Industry | undefined): string[] {
  return [
    ...(industry ? [SPECIFIC[industry]] : []),
    "Which Indian festivals in the next two months fit our brand, and what should we post?",
    "Research what's trending in our category this month, with sources",
    "Write 3 Instagram posts in our brand voice about what makes us different",
  ];
}

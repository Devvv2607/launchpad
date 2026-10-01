import type { Schemas } from "@/lib/api/client";

export type Industry = Schemas["Industry"];

export const INDUSTRY_LABELS: Record<Industry, { label: string; hint: string }> = {
  food: { label: "Food & beverage", hint: "Cafés, restaurants, bakeries, cloud kitchens" },
  fashion: { label: "Fashion", hint: "Apparel, footwear, jewellery, accessories" },
  beauty: { label: "Beauty & wellness", hint: "Salons, skincare, spas, cosmetics" },
  fitness: { label: "Fitness", hint: "Gyms, yoga studios, trainers, sports" },
  healthcare: { label: "Healthcare", hint: "Clinics, dentists, therapy, pharmacies" },
  education: { label: "Education", hint: "Coaching, courses, schools, edtech" },
  tech: { label: "Technology", hint: "SaaS, apps, IT services, startups" },
  finance: { label: "Finance", hint: "Advisors, insurance, lending, accounting" },
  real_estate: { label: "Real estate", hint: "Developers, brokers, rentals, co-living" },
  travel: { label: "Travel & hospitality", hint: "Hotels, homestays, tours, agencies" },
  automotive: { label: "Automotive", hint: "Dealers, service centres, rentals" },
  home: { label: "Home & interiors", hint: "Furniture, décor, renovation, appliances" },
  entertainment: { label: "Events & entertainment", hint: "Venues, music, gaming, events" },
  pet: { label: "Pet care", hint: "Vets, grooming, pet food, boarding" },
  retail: { label: "Retail", hint: "Stores, D2C brands, marketplaces" },
};

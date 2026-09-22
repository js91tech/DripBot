import { clamp, hashString, seededInt, seededUnit } from "@/lib/hash";
import type {
  FulfillmentModel,
  Persona,
  ResearchRequest,
  SaturationRisk,
  Verdict,
} from "@/lib/types";

const VIRAL_HINTS = [
  "tiktok",
  "viral",
  "led",
  "gadget",
  "fan",
  "light",
  "massage",
  "neck",
  "portable",
  "mini",
  "magnetic",
  "projector",
  "organizer",
  "stanley",
  "blush",
];

const DIGITAL_HINTS = [
  "ebook",
  "template",
  "course",
  "notion",
  "prompt",
  "swipe",
  "pdf",
  "software",
  "preset",
  "checklist",
  "planner",
  "midjourney",
  "canva",
];

const SATURATED_HINTS = [
  "phone case",
  "supplement",
  "vitamin",
  "water bottle",
  "yoga",
  "resistance band",
  "dropshipping",
  "generic",
];

const HIGH_MARGIN_HINTS = [
  "digital",
  "template",
  "course",
  "software",
  "print",
  "planner",
  "prompt",
];

function countHits(query: string, hints: string[]) {
  const q = query.toLowerCase();
  return hints.reduce((acc, hint) => acc + (q.includes(hint) ? 1 : 0), 0);
}

export function inferFulfillment(query: string): FulfillmentModel {
  return countHits(query, DIGITAL_HINTS) > 0 ? "DIGITAL" : "PHYSICAL";
}

export function scoreResearch(input: ResearchRequest) {
  const query = input.query.trim();
  const hash = hashString(query.toLowerCase());
  const fulfillment = inferFulfillment(query);
  const viralHits = countHits(query, VIRAL_HINTS);
  const digitalHits = countHits(query, DIGITAL_HINTS);
  const saturatedHits = countHits(query, SATURATED_HINTS);
  const marginHits = countHits(query, HIGH_MARGIN_HINTS);

  const viralCapability = clamp(
    38 + viralHits * 14 + seededInt(hash, 0, 22, 1) + (fulfillment === "DIGITAL" ? 6 : 0)
  );
  const competitionDensity = clamp(
    28 + saturatedHits * 18 + seededInt(hash, 8, 36, 2) - digitalHits * 6
  );
  const profitMarginPotential = clamp(
    (fulfillment === "DIGITAL" ? 72 : 48) +
      marginHits * 8 +
      seededInt(hash, -8, 16, 3) -
      saturatedHits * 7
  );

  const viabilityScore = clamp(
    profitMarginPotential * 0.4 + (100 - competitionDensity) * 0.3 + viralCapability * 0.3
  );

  let saturationRisk: SaturationRisk = "MEDIUM";
  if (competitionDensity >= 72) saturationRisk = "HIGH";
  else if (competitionDensity <= 45) saturationRisk = "LOW";

  let verdict: Verdict = "WATCH";
  if (viabilityScore >= 70 && saturationRisk !== "HIGH") verdict = "BUY";
  else if (viabilityScore < 48 || (saturationRisk === "HIGH" && profitMarginPotential < 55)) {
    verdict = "PASS";
  }

  const unitCost =
    fulfillment === "DIGITAL"
      ? Number((0.4 + seededUnit(hash, 4) * 2.2).toFixed(2))
      : Number((4.5 + seededUnit(hash, 4) * 18).toFixed(2));

  const marginPct =
    fulfillment === "DIGITAL"
      ? Number((78 + seededUnit(hash, 5) * 16).toFixed(1))
      : Number((32 + seededUnit(hash, 5) * 28 - saturatedHits * 4).toFixed(1));

  const priceMin =
    fulfillment === "DIGITAL"
      ? Number((9 + seededUnit(hash, 6) * 18).toFixed(2))
      : Number((unitCost * (1.8 + seededUnit(hash, 6))).toFixed(2));
  const priceMax = Number((priceMin * (1.35 + seededUnit(hash, 7) * 0.5)).toFixed(2));

  const demandSearchVolume = seededInt(hash, 12_000, 420_000, 8);
  const demandSocialMomentum = Number((35 + viralHits * 12 + seededUnit(hash, 9) * 40).toFixed(1));
  const demandAdActivity = seededInt(hash, 18, 92, 10);
  const supplyCompetitorCount = seededInt(hash, 40, 2800, 11) + saturatedHits * 400;

  const personas = buildPersonas(query, input.audience, fulfillment, hash);
  const niche = input.category || inferNiche(query, fulfillment);

  return {
    query,
    niche,
    category: input.category || niche,
    targetAudience: input.audience || personas[0]?.name || "Online shoppers",
    viabilityScore,
    profitMarginPotential,
    competitionDensity,
    viralCapability,
    recommendedPriceMin: priceMin,
    recommendedPriceMax: priceMax,
    personas,
    demandSearchVolume,
    demandSocialMomentum: clamp(demandSocialMomentum),
    demandAdActivity,
    supplyCompetitorCount,
    saturationRisk,
    verdict,
    predictedMarginPct: clamp(marginPct),
    fulfillmentHint: fulfillment,
    unitCostEstimate: unitCost,
  };
}

function inferNiche(query: string, fulfillment: FulfillmentModel) {
  if (fulfillment === "DIGITAL") return "Digital downloads";
  if (query.toLowerCase().includes("pet")) return "Pet accessories";
  if (query.toLowerCase().includes("home") || query.toLowerCase().includes("light")) {
    return "Home & lighting";
  }
  if (query.toLowerCase().includes("beauty") || query.toLowerCase().includes("skin")) {
    return "Beauty";
  }
  return "Consumer gadgets";
}

function buildPersonas(
  query: string,
  audience: string | undefined,
  fulfillment: FulfillmentModel,
  hash: number
): Persona[] {
  const digital: Persona[] = [
    {
      name: "Side-hustle Sam",
      ageRange: "24-34",
      channels: ["TikTok", "YouTube"],
      motivation: "Wants plug-and-play assets that can be resold or used immediately",
      willingnessToPay: "$12–$39 impulse buy",
    },
    {
      name: "Operator Olivia",
      ageRange: "28-42",
      channels: ["LinkedIn", "Email"],
      motivation: "Buys templates and systems to save hours each week",
      willingnessToPay: "$29–$79 if it replaces a tool",
    },
    {
      name: "Creator Kai",
      ageRange: "18-29",
      channels: ["Instagram", "Twitter/X"],
      motivation: `Needs ${query} to ship content faster`,
      willingnessToPay: "Will pay for aesthetics and speed",
    },
  ];

  const physical: Persona[] = [
    {
      name: "Impulse Isla",
      ageRange: "18-32",
      channels: ["TikTok Shop", "Instagram Reels"],
      motivation: "Shops visually; converts on UGC demos and before/after clips",
      willingnessToPay: "$14–$39 if shipping is under a week",
    },
    {
      name: "Home-upgrade Harper",
      ageRange: "30-48",
      channels: ["Amazon", "Facebook"],
      motivation: "Solves a household annoyance with a compact gadget",
      willingnessToPay: "Pays extra for US/EU warehouse shipping",
    },
    {
      name: "Gift-buyer Gabe",
      ageRange: "25-44",
      channels: ["Google", "Etsy"],
      motivation: `Looks for unique ${query} gifts with fast delivery`,
      willingnessToPay: "Premium if packaging looks gift-ready",
    },
  ];

  const base = fulfillment === "DIGITAL" ? digital : physical;
  if (audience) {
    base[0] = {
      ...base[0],
      name: audience,
      motivation: `Primary target: ${audience} researching ${query}`,
    };
  }
  const offset = seededInt(hash, 0, base.length - 1, 20);
  return [0, 1, 2].map((i) => base[(i + offset) % base.length]);
}

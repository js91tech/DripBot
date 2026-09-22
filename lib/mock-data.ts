import { hashString, seededInt, seededUnit } from "@/lib/hash";
import type { MonthlyPoint, PlatformTrend } from "@/lib/types";

const PLATFORMS = ["TikTok Shop", "Etsy", "Amazon", "Google Trends"] as const;

const LISTING_BANK: Record<(typeof PLATFORMS)[number], (query: string) => string[]> = {
  "TikTok Shop": (q) => [
    `Viral ${q} — 2026 restock`,
    `${q} that actually works (UGC bundle)`,
    `Mini ${q} for desk / car / travel`,
  ],
  Etsy: (q) => [
    `Handmade-style ${q} listing template`,
    `Personalized ${q} gift version`,
    `Premium ${q} with gift wrap add-on`,
  ],
  Amazon: (q) => [
    `${q} - 2 pack, prime-eligible angle`,
    `Budget ${q} with 4.3★ social proof`,
    `${q} accessory bundle (upsell)`,
  ],
  "Google Trends": (q) => [
    `${q} near me / best ${q} 2026`,
    `${q} vs alternatives comparison`,
    `How to use ${q} (content demand)`,
  ],
};

export function buildPlatformTrends(query: string): PlatformTrend[] {
  const hash = hashString(query.toLowerCase());
  return PLATFORMS.map((platform, index) => ({
    platform,
    searchVolume: seededInt(hash, 8_000, 380_000, 30 + index),
    searchVolumeDelta: Number((-18 + seededUnit(hash, 40 + index) * 54).toFixed(1)),
    socialMomentum: Number((20 + seededUnit(hash, 50 + index) * 75).toFixed(1)),
    adActivityScore: seededInt(hash, 12, 96, 60 + index),
    sampleListings: LISTING_BANK[platform](query),
  }));
}

export function buildMonthlyTrend(query: string): MonthlyPoint[] {
  const hash = hashString(query.toLowerCase());
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  let demand = 40 + seededInt(hash, 0, 25, 70);
  let saturation = 30 + seededInt(hash, 0, 20, 71);
  return months.map((month, index) => {
    demand = Math.max(12, Math.min(98, demand + seededInt(hash, -8, 12, 80 + index)));
    saturation = Math.max(10, Math.min(95, saturation + seededInt(hash, -6, 9, 90 + index)));
    return { month, demand, saturation };
  });
}

export function mockSummary(input: {
  query: string;
  verdict: string;
  viabilityScore: number;
  saturationRisk: string;
  predictedMarginPct: number;
  fulfillmentHint: string;
}) {
  const tone =
    input.verdict === "BUY"
      ? "There is a commercially interesting window if you list quickly and keep ads creative-led."
      : input.verdict === "PASS"
        ? "I would not allocate inventory or ad budget here without a sharp differentiator."
        : "Treat this as a test listing: small batch, fast creative iteration, kill if CAC stays high.";

  return `${input.query} scores ${input.viabilityScore}/100 on CommercePulse. Predicted margin is about ${input.predictedMarginPct}% as a ${input.fulfillmentHint.toLowerCase()} offer, with ${input.saturationRisk.toLowerCase()} supply saturation. ${tone} Pair local-warehouse SKUs with UGC-style creative, and avoid racing the most generic Amazon title.`;
}

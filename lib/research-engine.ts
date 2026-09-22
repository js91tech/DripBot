import { enrichWithLlm } from "@/lib/ai";
import { buildMonthlyTrend, buildPlatformTrends, mockSummary } from "@/lib/mock-data";
import { fetchNewsHeadlines, fetchSerpShopping, mergeLiveListings } from "@/lib/providers/live-data";
import { scoreResearch } from "@/lib/scoring";
import type { DataSource, ResearchRequest, ResearchResult } from "@/lib/types";

export async function runResearch(input: ResearchRequest): Promise<ResearchResult> {
  const query = input.query.trim();
  if (query.length < 2) {
    throw new Error("Enter a niche, product, or audience with at least 2 characters.");
  }

  const scored = scoreResearch({ ...input, query });
  const platforms = buildPlatformTrends(query);
  const monthlyTrend = buildMonthlyTrend(query);
  const sources: DataSource[] = [
    { name: "CommercePulse scoring engine", type: "fallback", detail: "Deterministic viability model" },
  ];

  const [news, shopping] = await Promise.all([
    fetchNewsHeadlines(query),
    fetchSerpShopping(query),
  ]);

  if (news.source) sources.push(news.source);
  if (shopping.source) sources.push(shopping.source);

  const mergedPlatforms = mergeLiveListings(platforms, shopping.listings);
  if (news.headlines.length) {
    const google = mergedPlatforms.find((p) => p.platform === "Google Trends");
    if (google) google.sampleListings = news.headlines.slice(0, 4);
  }

  const usedLiveData = sources.some((source) => source.type === "live");

  const draft: ResearchResult = {
    ...scored,
    summary: mockSummary(scored),
    sources,
    monthlyTrend,
    platforms: mergedPlatforms,
    usedLiveData,
    usedLlm: false,
  };

  const llm = await enrichWithLlm(draft);
  if (llm.source) draft.sources.push(llm.source);

  return {
    ...draft,
    summary: llm.summary,
    personas: llm.personas,
    usedLlm: llm.usedLlm,
  };
}

export function demandSnapshot(result: Pick<
  ResearchResult,
  | "demandSearchVolume"
  | "demandSocialMomentum"
  | "demandAdActivity"
  | "supplyCompetitorCount"
  | "saturationRisk"
  | "verdict"
  | "predictedMarginPct"
  | "viabilityScore"
>) {
  return {
    demand: {
      searchVolume: result.demandSearchVolume,
      socialMomentum: result.demandSocialMomentum,
      adActivityScore: result.demandAdActivity,
    },
    supply: {
      competitorStores: result.supplyCompetitorCount,
      saturationRisk: result.saturationRisk,
    },
    verdict: result.verdict,
    predictedMarginPct: result.predictedMarginPct,
    viabilityScore: result.viabilityScore,
  };
}

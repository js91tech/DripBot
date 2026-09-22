import type { ResearchReport, MarketTrend } from "@prisma/client";
import type { MonthlyPoint, Persona, PlatformTrend, ResearchResult } from "@/lib/types";
import { parseJson } from "@/lib/format";

export function serializeReport(result: ResearchResult) {
  return {
    query: result.query,
    niche: result.niche,
    category: result.category,
    targetAudience: result.targetAudience,
    viabilityScore: result.viabilityScore,
    profitMarginPotential: result.profitMarginPotential,
    competitionDensity: result.competitionDensity,
    viralCapability: result.viralCapability,
    recommendedPriceMin: result.recommendedPriceMin,
    recommendedPriceMax: result.recommendedPriceMax,
    personas: JSON.stringify(result.personas),
    demandSearchVolume: result.demandSearchVolume,
    demandSocialMomentum: result.demandSocialMomentum,
    demandAdActivity: result.demandAdActivity,
    supplyCompetitorCount: result.supplyCompetitorCount,
    saturationRisk: result.saturationRisk,
    verdict: result.verdict,
    predictedMarginPct: result.predictedMarginPct,
    summary: result.summary,
    sources: JSON.stringify(result.sources),
    monthlyTrend: JSON.stringify(result.monthlyTrend),
    usedLiveData: result.usedLiveData,
    usedLlm: result.usedLlm,
  };
}

export function hydrateReport(
  report: ResearchReport & { trends?: MarketTrend[] }
): ResearchResult {
  const trends = report.trends ?? [];
  return {
    query: report.query,
    niche: report.niche ?? report.category ?? "General",
    category: report.category ?? "General",
    targetAudience: report.targetAudience ?? "Online shoppers",
    viabilityScore: report.viabilityScore,
    profitMarginPotential: report.profitMarginPotential,
    competitionDensity: report.competitionDensity,
    viralCapability: report.viralCapability,
    recommendedPriceMin: report.recommendedPriceMin,
    recommendedPriceMax: report.recommendedPriceMax,
    personas: parseJson<Persona[]>(report.personas, []),
    demandSearchVolume: report.demandSearchVolume,
    demandSocialMomentum: report.demandSocialMomentum,
    demandAdActivity: report.demandAdActivity,
    supplyCompetitorCount: report.supplyCompetitorCount,
    saturationRisk: report.saturationRisk,
    verdict: report.verdict,
    predictedMarginPct: report.predictedMarginPct,
    summary: report.summary,
    sources: parseJson(report.sources, []),
    monthlyTrend: parseJson<MonthlyPoint[]>(report.monthlyTrend, []),
    platforms: trends.map((trend) => ({
      platform: trend.platform,
      searchVolume: trend.searchVolume,
      searchVolumeDelta: trend.searchVolumeDelta,
      socialMomentum: trend.socialMomentum,
      adActivityScore: trend.adActivityScore,
      sampleListings: parseJson<string[]>(trend.sampleListings, []),
    })) satisfies PlatformTrend[],
    usedLiveData: report.usedLiveData,
    usedLlm: report.usedLlm,
    fulfillmentHint: report.query.toLowerCase().match(/template|ebook|course|notion|prompt/)
      ? "DIGITAL"
      : "PHYSICAL",
    unitCostEstimate: Number((report.recommendedPriceMin * 0.35).toFixed(2)),
  };
}

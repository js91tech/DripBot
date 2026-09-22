"use server";

import { revalidatePath } from "next/cache";
import { prisma } from "@/lib/prisma";
import { runResearch } from "@/lib/research-engine";
import { serializeReport } from "@/lib/report-mapper";

export async function createResearchReport(formData: FormData) {
  const query = String(formData.get("query") ?? "").trim();
  const category = String(formData.get("category") ?? "").trim() || undefined;
  const audience = String(formData.get("audience") ?? "").trim() || undefined;
  if (query.length < 2) {
    return { error: "Enter a niche or product keyword." };
  }
  const result = await runResearch({ query, category, audience });
  const saved = await prisma.researchReport.create({
    data: {
      ...serializeReport(result),
      trends: {
        create: result.platforms.map((platform) => ({
          keyword: result.query,
          platform: platform.platform,
          searchVolume: platform.searchVolume,
          searchVolumeDelta: platform.searchVolumeDelta,
          socialMomentum: platform.socialMomentum,
          adActivityScore: platform.adActivityScore,
          sampleListings: JSON.stringify(platform.sampleListings),
        })),
      },
    },
  });
  revalidatePath("/");
  revalidatePath("/research");
  return { id: saved.id };
}

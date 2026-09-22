import { NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";
import { runResearch } from "@/lib/research-engine";
import { serializeReport } from "@/lib/report-mapper";
import { hydrateReport } from "@/lib/report-mapper";

export const dynamic = "force-dynamic";

export async function GET() {
  const reports = await prisma.researchReport.findMany({
    orderBy: { createdAt: "desc" },
    take: 40,
    include: { trends: true },
  });
  return NextResponse.json({
    reports: reports.map((report) => ({
      id: report.id,
      createdAt: report.createdAt,
      ...hydrateReport(report),
    })),
  });
}

export async function POST(request: Request) {
  const body = (await request.json()) as {
    query?: string;
    category?: string;
    audience?: string;
  };
  const query = body.query?.trim();
  if (!query) {
    return NextResponse.json({ error: "query is required" }, { status: 400 });
  }

  const result = await runResearch({
    query,
    category: body.category?.trim() || undefined,
    audience: body.audience?.trim() || undefined,
  });

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
    include: { trends: true },
  });

  return NextResponse.json({ id: saved.id, createdAt: saved.createdAt, ...hydrateReport(saved) });
}

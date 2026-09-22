import { NextResponse } from "next/server";
import { demandSnapshot, runResearch } from "@/lib/research-engine";
import { matchSuppliers } from "@/lib/supplier-engine";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const query = new URL(request.url).searchParams.get("query")?.trim();
  if (!query) {
    return NextResponse.json({ error: "query is required" }, { status: 400 });
  }
  const result = await runResearch({ query });
  return NextResponse.json({
    query,
    ...demandSnapshot(result),
    recommendedPriceMin: result.recommendedPriceMin,
    recommendedPriceMax: result.recommendedPriceMax,
    suppliers: matchSuppliers(query, 5),
    summary: result.summary,
  });
}

export async function POST(request: Request) {
  const body = (await request.json()) as { query?: string };
  const query = body.query?.trim();
  if (!query) {
    return NextResponse.json({ error: "query is required" }, { status: 400 });
  }
  const result = await runResearch({ query });
  return NextResponse.json({
    query,
    ...demandSnapshot(result),
    platforms: result.platforms,
    monthlyTrend: result.monthlyTrend,
    recommendedPriceMin: result.recommendedPriceMin,
    recommendedPriceMax: result.recommendedPriceMax,
    suppliers: matchSuppliers(query, 5),
    summary: result.summary,
  });
}

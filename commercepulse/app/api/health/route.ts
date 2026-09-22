import { NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    await prisma.$queryRaw`SELECT 1`;
    return NextResponse.json({
      ok: true,
      service: "CommercePulse",
      database: "up",
      llm: Boolean(process.env.OPENAI_API_KEY || process.env.ANTHROPIC_API_KEY),
      serpapi: Boolean(process.env.SERPAPI_KEY),
    });
  } catch (error) {
    return NextResponse.json(
      { ok: false, database: "down", error: error instanceof Error ? error.message : "unknown" },
      { status: 503 }
    );
  }
}

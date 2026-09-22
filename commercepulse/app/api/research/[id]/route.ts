import { NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";
import { hydrateReport } from "@/lib/report-mapper";

export const dynamic = "force-dynamic";

export async function GET(
  _request: Request,
  context: { params: Promise<{ id: string }> }
) {
  const { id } = await context.params;
  const report = await prisma.researchReport.findUnique({
    where: { id },
    include: { trends: true },
  });
  if (!report) {
    return NextResponse.json({ error: "Report not found" }, { status: 404 });
  }
  return NextResponse.json({ id: report.id, createdAt: report.createdAt, ...hydrateReport(report) });
}

import { prisma } from "@/lib/prisma";
import { hydrateReport } from "@/lib/report-mapper";
import { ReportCard } from "@/components/research/report-card";
import { ResearchBar } from "@/components/research/research-bar";

export const dynamic = "force-dynamic";

export default async function ResearchPage() {
  const reports = await prisma.researchReport.findMany({
    orderBy: { createdAt: "desc" },
    include: { trends: true },
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Market research</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Score a niche across TikTok Shop, Etsy, Amazon, and Google Trends — with a mock engine that still runs offline.
        </p>
      </div>
      <ResearchBar />
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {reports.map((report) => (
          <ReportCard key={report.id} id={report.id} createdAt={report.createdAt} report={hydrateReport(report)} />
        ))}
      </div>
    </div>
  );
}

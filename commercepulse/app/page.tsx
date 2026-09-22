import Link from "next/link";
import { prisma } from "@/lib/prisma";
import { hydrateReport } from "@/lib/report-mapper";
import { ResearchBar } from "@/components/research/research-bar";
import { ReportCard } from "@/components/research/report-card";
import { DemandSaturationChart } from "@/components/research/demand-saturation";
import { MetricBar, VerdictBadge, ViabilityGauge } from "@/components/research/viability-gauge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { compactNumber, money } from "@/lib/format";

export const dynamic = "force-dynamic";

export default async function DashboardPage() {
  const [reports, products, suppliers] = await Promise.all([
    prisma.researchReport.findMany({
      orderBy: { createdAt: "desc" },
      take: 6,
      include: { trends: true },
    }),
    prisma.product.findMany(),
    prisma.supplier.findMany(),
  ]);

  const latest = reports[0] ? hydrateReport(reports[0]) : null;
  const avgViability = reports.length
    ? Math.round(reports.reduce((sum, report) => sum + report.viabilityScore, 0) / reports.length)
    : 0;
  const buyCount = reports.filter((report) => report.verdict === "BUY").length;
  const digitalCount = products.filter((product) => product.fulfillmentModel === "DIGITAL").length;

  return (
    <div className="space-y-8">
      <section className="relative overflow-hidden rounded-3xl border border-border bg-card/40 p-6 pulse-grid md:p-10">
        <p className="text-xs font-medium tracking-[0.2em] text-primary uppercase">CommercePulse</p>
        <h1 className="mt-2 max-w-2xl text-3xl font-semibold tracking-tight md:text-4xl">
          Find the product. Score the market. Source it locally.
        </h1>
        <p className="mt-3 max-w-2xl text-sm text-muted-foreground md:text-base">
          Automated research for digital downloads and physical dropshipping — viability scores, demand vs saturation,
          and warehouse-aware supplier matching.
        </p>
        <div className="mt-6">
          <ResearchBar />
        </div>
      </section>

      <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Kpi label="Reports in vault" value={String(reports.length)} hint="Saved research runs" />
        <Kpi label="Avg viability" value={String(avgViability)} hint="Across recent queries" />
        <Kpi label="Buy verdicts" value={String(buyCount)} hint="Green-lit opportunities" />
        <Kpi
          label="Catalog mix"
          value={`${digitalCount}/${products.length - digitalCount}`}
          hint="Digital / physical SKUs"
        />
      </section>

      {latest && reports[0] ? (
        <section className="grid gap-4 lg:grid-cols-[0.9fr_1.1fr]">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center justify-between gap-3">
                <span className="capitalize">{latest.query}</span>
                <VerdictBadge verdict={latest.verdict} />
              </CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col items-center gap-6 sm:flex-row">
              <ViabilityGauge value={latest.viabilityScore} />
              <div className="w-full space-y-3">
                <MetricBar label="Profit margin potential" value={latest.profitMarginPotential} tone="teal" />
                <MetricBar label="Competition density" value={latest.competitionDensity} tone="rose" />
                <MetricBar label="Viral capability" value={latest.viralCapability} tone="amber" />
                <p className="text-xs text-muted-foreground">
                  List {money(latest.recommendedPriceMin)}–{money(latest.recommendedPriceMax)} ·{" "}
                  {compactNumber(latest.demandSearchVolume)} search · {suppliers.length} suppliers on file
                </p>
                <Link href={`/research/${reports[0].id}`} className="text-sm text-primary hover:underline">
                  Open full report
                </Link>
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>Demand vs saturation</CardTitle>
            </CardHeader>
            <CardContent>
              <DemandSaturationChart data={latest.monthlyTrend} />
            </CardContent>
          </Card>
        </section>
      ) : null}

      <section>
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-medium">Recent research</h2>
          <Link href="/research" className="text-sm text-primary hover:underline">
            View all
          </Link>
        </div>
        {reports.length ? (
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {reports.map((report) => (
              <ReportCard
                key={report.id}
                id={report.id}
                createdAt={report.createdAt}
                report={hydrateReport(report)}
              />
            ))}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">
            Run a keyword above. Seed data appears after <code>npm run db:setup</code>.
          </p>
        )}
      </section>
    </div>
  );
}

function Kpi({ label, value, hint }: { label: string; value: string; hint: string }) {
  return (
    <Card>
      <CardContent className="gap-1">
        <div className="text-xs text-muted-foreground">{label}</div>
        <div className="text-2xl font-semibold tracking-tight">{value}</div>
        <div className="text-xs text-muted-foreground">{hint}</div>
      </CardContent>
    </Card>
  );
}

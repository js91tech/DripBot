import { notFound } from "next/navigation";
import Link from "next/link";
import { prisma } from "@/lib/prisma";
import { hydrateReport } from "@/lib/report-mapper";
import { matchSuppliers } from "@/lib/supplier-engine";
import { compactNumber, money, saturationCopy } from "@/lib/format";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { DemandSaturationChart } from "@/components/research/demand-saturation";
import { MetricBar, VerdictBadge, ViabilityGauge } from "@/components/research/viability-gauge";
import { SupplierTable } from "@/components/suppliers/supplier-table";

export const dynamic = "force-dynamic";

export default async function ResearchDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const report = await prisma.researchReport.findUnique({
    where: { id },
    include: { trends: true },
  });
  if (!report) notFound();
  const data = hydrateReport(report);
  const suppliers = matchSuppliers(data.query, 6);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-xs tracking-[0.18em] text-muted-foreground uppercase">Research report</p>
          <h1 className="mt-1 text-3xl font-semibold capitalize">{data.query}</h1>
          <p className="mt-2 max-w-3xl text-sm text-muted-foreground">{data.summary}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <VerdictBadge verdict={data.verdict} />
          <Badge variant="secondary">{saturationCopy(data.saturationRisk)}</Badge>
          {data.usedLiveData ? <Badge variant="outline">Live data</Badge> : <Badge variant="outline">Mock engine</Badge>}
          {data.usedLlm ? <Badge variant="outline">LLM summary</Badge> : null}
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-[0.8fr_1.2fr]">
        <Card>
          <CardContent className="flex flex-col items-center gap-4 py-6">
            <ViabilityGauge value={data.viabilityScore} />
            <div className="w-full space-y-3">
              <MetricBar label="Profit margin potential" value={data.profitMarginPotential} tone="teal" />
              <MetricBar label="Competition density" value={data.competitionDensity} tone="rose" />
              <MetricBar label="Viral marketing capability" value={data.viralCapability} tone="amber" />
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Demand vs saturation</CardTitle>
          </CardHeader>
          <CardContent>
            <DemandSaturationChart data={data.monthlyTrend} />
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <Stat title="Search volume" value={compactNumber(data.demandSearchVolume)} hint="Modeled monthly queries" />
        <Stat title="Social momentum" value={`${data.demandSocialMomentum}`} hint="Short-form + marketplace buzz" />
        <Stat title="Ad activity" value={`${data.demandAdActivity}`} hint="Paid competition index" />
        <Stat
          title="Competitor stores"
          value={compactNumber(data.supplyCompetitorCount)}
          hint={`${saturationCopy(data.saturationRisk)}`}
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Pricing & margin</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            <p>
              Recommended list price{" "}
              <strong>
                {money(data.recommendedPriceMin)} – {money(data.recommendedPriceMax)}
              </strong>
            </p>
            <p>Predicted margin {data.predictedMarginPct}% as a {data.fulfillmentHint.toLowerCase()} offer.</p>
            <p className="text-muted-foreground">
              Unit cost estimate {money(data.unitCostEstimate)}. Use local warehouses if ads depend on 2–5 day delivery.
            </p>
            <Link href="/builder" className="inline-block text-primary hover:underline">
              Send to product builder
            </Link>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Target personas</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-3">
            {data.personas.map((persona) => (
              <div key={persona.name} className="rounded-xl border border-border/80 p-3">
                <div className="font-medium">{persona.name}</div>
                <div className="text-xs text-muted-foreground">
                  {persona.ageRange} · {persona.channels.join(", ")}
                </div>
                <p className="mt-1 text-sm">{persona.motivation}</p>
                <p className="mt-1 text-xs text-primary">{persona.willingnessToPay}</p>
              </div>
            ))}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Platform signals</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4 md:grid-cols-2">
          {data.platforms.map((platform) => (
            <div key={platform.platform} className="rounded-xl border border-border/70 p-4">
              <div className="flex items-center justify-between">
                <div className="font-medium">{platform.platform}</div>
                <span className={`text-xs ${platform.searchVolumeDelta >= 0 ? "text-teal-300" : "text-rose-300"}`}>
                  {platform.searchVolumeDelta >= 0 ? "+" : ""}
                  {platform.searchVolumeDelta}%
                </span>
              </div>
              <p className="mt-1 text-xs text-muted-foreground">
                {compactNumber(platform.searchVolume)} volume · ads {platform.adActivityScore} · momentum{" "}
                {Math.round(platform.socialMomentum)}
              </p>
              <ul className="mt-3 space-y-1 text-sm text-muted-foreground">
                {platform.sampleListings.map((listing) => (
                  <li key={listing}>• {listing}</li>
                ))}
              </ul>
            </div>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Suggested suppliers</CardTitle>
        </CardHeader>
        <CardContent>
          <SupplierTable suppliers={suppliers} />
        </CardContent>
      </Card>

      <p className="text-xs text-muted-foreground">
        Sources: {data.sources.map((source) => source.name).join(" · ")}
      </p>
    </div>
  );
}

function Stat({ title, value, hint }: { title: string; value: string; hint: string }) {
  return (
    <Card>
      <CardContent>
        <div className="text-xs text-muted-foreground">{title}</div>
        <div className="mt-1 text-2xl font-semibold">{value}</div>
        <div className="text-xs text-muted-foreground">{hint}</div>
      </CardContent>
    </Card>
  );
}

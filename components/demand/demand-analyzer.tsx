"use client";

import { useState } from "react";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { DemandSaturationChart } from "@/components/research/demand-saturation";
import { MetricBar, VerdictBadge } from "@/components/research/viability-gauge";
import { SupplierTable } from "@/components/suppliers/supplier-table";
import { compactNumber, money } from "@/lib/format";
import type { MonthlyPoint, PlatformTrend, SaturationRisk, SupplierRecord, Verdict } from "@/lib/types";

type DemandResponse = {
  query: string;
  demand: { searchVolume: number; socialMomentum: number; adActivityScore: number };
  supply: { competitorStores: number; saturationRisk: SaturationRisk };
  verdict: Verdict;
  predictedMarginPct: number;
  viabilityScore: number;
  recommendedPriceMin: number;
  recommendedPriceMax: number;
  suppliers: SupplierRecord[];
  summary: string;
  monthlyTrend?: MonthlyPoint[];
  platforms?: PlatformTrend[];
};

export function DemandAnalyzer() {
  const [query, setQuery] = useState("portable neck fan");
  const [pending, setPending] = useState(false);
  const [result, setResult] = useState<DemandResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function run() {
    setPending(true);
    setError(null);
    try {
      const response = await fetch("/api/demand", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Demand analysis failed");
      setResult(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Demand analysis failed");
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="space-y-6">
      <form
        className="flex max-w-2xl gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          void run();
        }}
      >
        <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Product or niche" />
        <Button type="submit" disabled={pending}>
          {pending ? <Loader2 className="size-4 animate-spin" /> : null}
          Score demand
        </Button>
      </form>
      {error ? <p className="text-sm text-destructive">{error}</p> : null}
      {result ? (
        <>
          <div className="grid gap-4 lg:grid-cols-3">
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center justify-between">
                  Verdict
                  <VerdictBadge verdict={result.verdict} />
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="text-4xl font-semibold">{result.viabilityScore}</div>
                <p className="text-sm text-muted-foreground">{result.summary}</p>
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle>Demand</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <MetricBar label="Search volume index" value={Math.min(100, result.demand.searchVolume / 4000)} tone="teal" />
                <MetricBar label="Social momentum" value={result.demand.socialMomentum} tone="blue" />
                <MetricBar label="Ad activity" value={result.demand.adActivityScore} tone="amber" />
                <p className="text-xs text-muted-foreground">
                  Est. search volume {compactNumber(result.demand.searchVolume)}
                </p>
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle>Supply</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <MetricBar
                  label="Saturation risk"
                  value={result.supply.saturationRisk === "HIGH" ? 82 : result.supply.saturationRisk === "MEDIUM" ? 55 : 28}
                  tone="rose"
                />
                <p className="text-sm">
                  {compactNumber(result.supply.competitorStores)} active competitor listings
                </p>
                <p className="text-sm text-muted-foreground">
                  Predicted margin {result.predictedMarginPct}% · list {money(result.recommendedPriceMin)}–
                  {money(result.recommendedPriceMax)}
                </p>
              </CardContent>
            </Card>
          </div>
          {result.monthlyTrend ? (
            <Card>
              <CardHeader>
                <CardTitle>Demand vs saturation</CardTitle>
              </CardHeader>
              <CardContent>
                <DemandSaturationChart data={result.monthlyTrend} />
              </CardContent>
            </Card>
          ) : null}
          <Card>
            <CardHeader>
              <CardTitle>Matched suppliers</CardTitle>
            </CardHeader>
            <CardContent>
              <SupplierTable suppliers={result.suppliers} />
            </CardContent>
          </Card>
        </>
      ) : (
        <p className="text-sm text-muted-foreground">
          Run a keyword to compute search momentum, competitor density, and a Buy / Watch / Pass verdict.
        </p>
      )}
    </div>
  );
}

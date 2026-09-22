import Link from "next/link";
import { Card, CardContent } from "@/components/ui/card";
import { VerdictBadge } from "@/components/research/viability-gauge";
import { compactNumber, money, relativeTime } from "@/lib/format";
import type { ResearchResult, Verdict } from "@/lib/types";

export function ReportCard({
  id,
  createdAt,
  report,
}: {
  id: string;
  createdAt: Date | string;
  report: ResearchResult;
}) {
  return (
    <Link href={`/research/${id}`}>
      <Card className="h-full transition hover:ring-primary/30">
        <CardContent className="flex flex-col gap-3">
          <div className="flex items-start justify-between gap-3">
            <div>
              <div className="font-medium capitalize">{report.query}</div>
              <div className="text-xs text-muted-foreground">{relativeTime(createdAt)}</div>
            </div>
            <VerdictBadge verdict={report.verdict as Verdict} />
          </div>
          <div className="grid grid-cols-3 gap-2 text-xs">
            <Stat label="Viability" value={`${report.viabilityScore}`} />
            <Stat label="Demand" value={compactNumber(report.demandSearchVolume)} />
            <Stat
              label="Price"
              value={`${money(report.recommendedPriceMin)}–${money(report.recommendedPriceMax)}`}
            />
          </div>
        </CardContent>
      </Card>
    </Link>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg bg-muted/40 px-2 py-1.5">
      <div className="text-[10px] tracking-wide text-muted-foreground uppercase">{label}</div>
      <div className="font-medium">{value}</div>
    </div>
  );
}

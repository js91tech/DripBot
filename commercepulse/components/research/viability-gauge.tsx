import { cn } from "@/lib/utils";
import type { Verdict } from "@/lib/types";
import { verdictCopy } from "@/lib/format";
import { Badge } from "@/components/ui/badge";

export function ViabilityGauge({
  value,
  size = 180,
}: {
  value: number;
  size?: number;
}) {
  const radius = 68;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (Math.min(100, Math.max(0, value)) / 100) * circumference;
  const color = value >= 70 ? "#2dd4bf" : value >= 50 ? "#fbbf24" : "#fb7185";

  return (
    <div className="relative" style={{ width: size, height: size }}>
      <svg viewBox="0 0 180 180" className="size-full -rotate-90">
        <circle cx="90" cy="90" r={radius} fill="none" stroke="currentColor" strokeWidth="12" className="text-muted/60" />
        <circle
          cx="90"
          cy="90"
          r={radius}
          fill="none"
          stroke={color}
          strokeWidth="12"
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <div className="text-4xl font-semibold tracking-tight">{value}</div>
        <div className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground">Viability</div>
      </div>
    </div>
  );
}

export function MetricBar({
  label,
  value,
  tone = "teal",
}: {
  label: string;
  value: number;
  tone?: "teal" | "amber" | "rose" | "blue";
}) {
  const tones = {
    teal: "bg-teal-400",
    amber: "bg-amber-400",
    rose: "bg-rose-400",
    blue: "bg-sky-400",
  };
  return (
    <div>
      <div className="mb-1 flex items-center justify-between text-xs">
        <span className="text-muted-foreground">{label}</span>
        <span className="font-medium tabular-nums">{Math.round(value)}</span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-muted">
        <div className={cn("h-full rounded-full", tones[tone])} style={{ width: `${Math.min(100, value)}%` }} />
      </div>
    </div>
  );
}

export function VerdictBadge({ verdict }: { verdict: Verdict }) {
  const copy = verdictCopy(verdict);
  const styles: Record<Verdict, string> = {
    BUY: "bg-teal-400/15 text-teal-300 border-teal-400/20",
    WATCH: "bg-amber-400/15 text-amber-200 border-amber-400/20",
    PASS: "bg-rose-400/15 text-rose-300 border-rose-400/20",
  };
  return (
    <Badge variant="outline" className={cn("border px-2.5", styles[verdict])}>
      {copy.label}
    </Badge>
  );
}

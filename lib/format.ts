import { formatDistanceToNow } from "date-fns";
import type { SaturationRisk, Verdict, WarehouseRegion } from "@/lib/types";

export function money(value: number, currency = "USD") {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    maximumFractionDigits: value >= 100 ? 0 : 2,
  }).format(value);
}

export function compactNumber(value: number) {
  return new Intl.NumberFormat("en-US", {
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(value);
}

export function relativeTime(date: Date | string) {
  return formatDistanceToNow(new Date(date), { addSuffix: true });
}

export function regionLabel(region: WarehouseRegion) {
  const labels: Record<WarehouseRegion, string> = {
    US: "United States",
    UK: "United Kingdom",
    EU: "European Union",
    GLOBAL: "Global / mixed",
    CN: "China / overseas",
  };
  return labels[region];
}

export function verdictCopy(verdict: Verdict) {
  const copy: Record<Verdict, { label: string; hint: string }> = {
    BUY: { label: "Buy", hint: "Healthy demand with workable supply" },
    WATCH: { label: "Watch", hint: "Promising but not a clear green light" },
    PASS: { label: "Pass", hint: "Saturation or thin margin outweighs demand" },
  };
  return copy[verdict];
}

export function saturationCopy(risk: SaturationRisk) {
  const copy: Record<SaturationRisk, string> = {
    LOW: "Low saturation",
    MEDIUM: "Medium saturation",
    HIGH: "High saturation",
  };
  return copy[risk];
}

export function slugify(value: string) {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/(^-|-$)+/g, "")
    .slice(0, 60);
}

export function parseJson<T>(raw: string, fallback: T): T {
  try {
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

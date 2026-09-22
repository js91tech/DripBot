import type { SupplierRecord, WarehouseRegion } from "@/lib/types";
import { hashString, seededInt, seededUnit } from "@/lib/hash";
import { inferFulfillment } from "@/lib/scoring";

export const CATALOG_SUPPLIERS: SupplierRecord[] = [
  {
    name: "HarborLink Fulfillment",
    warehouseLocation: "Los Angeles, CA",
    region: "US",
    estimatedShippingDaysMin: 2,
    estimatedShippingDaysMax: 5,
    unitCost: 7.4,
    moq: 1,
    returnPolicy: "30-day defective replacement, buyer pays return freight",
    website: "https://example.com/harborlink",
    rating: 4.8,
    verified: true,
    categories: ["gadgets", "home", "lighting"],
  },
  {
    name: "Maple & Broad Co.",
    warehouseLocation: "Newark, NJ",
    region: "US",
    estimatedShippingDaysMin: 2,
    estimatedShippingDaysMax: 4,
    unitCost: 8.1,
    moq: 5,
    returnPolicy: "14-day unopened returns",
    website: "https://example.com/maple-broad",
    rating: 4.6,
    verified: true,
    categories: ["home", "kitchen", "gifts"],
  },
  {
    name: "ShipNest UK",
    warehouseLocation: "Leicester, UK",
    region: "UK",
    estimatedShippingDaysMin: 2,
    estimatedShippingDaysMax: 5,
    unitCost: 6.9,
    moq: 1,
    returnPolicy: "UK consumer 14-day cooling-off for unopened goods",
    website: "https://example.com/shipnest",
    rating: 4.5,
    verified: true,
    categories: ["beauty", "gadgets", "pet"],
  },
  {
    name: "Nordic Node Logistics",
    warehouseLocation: "Eindhoven, NL",
    region: "EU",
    estimatedShippingDaysMin: 3,
    estimatedShippingDaysMax: 6,
    unitCost: 7.8,
    moq: 10,
    returnPolicy: "EU 14-day distance-selling returns",
    website: "https://example.com/nordic-node",
    rating: 4.7,
    verified: true,
    categories: ["home", "digital-print", "gadgets"],
  },
  {
    name: "Vistula Warehouse",
    warehouseLocation: "Poznań, PL",
    region: "EU",
    estimatedShippingDaysMin: 3,
    estimatedShippingDaysMax: 7,
    unitCost: 5.6,
    moq: 20,
    returnPolicy: "Defective-only returns within 21 days",
    website: "https://example.com/vistula",
    rating: 4.3,
    verified: false,
    categories: ["gadgets", "pet", "fitness"],
  },
  {
    name: "Pearl River Sourcing",
    warehouseLocation: "Shenzhen, CN",
    region: "CN",
    estimatedShippingDaysMin: 12,
    estimatedShippingDaysMax: 24,
    unitCost: 3.15,
    moq: 50,
    returnPolicy: "Replacement for factory defects only, no buyer-remorse returns",
    website: "https://example.com/pearl-river",
    rating: 4.2,
    verified: true,
    categories: ["electronics", "gadgets", "lighting"],
  },
  {
    name: "Yiwu Direct Hub",
    warehouseLocation: "Yiwu, CN",
    region: "CN",
    estimatedShippingDaysMin: 14,
    estimatedShippingDaysMax: 28,
    unitCost: 2.4,
    moq: 100,
    returnPolicy: "No returns on custom SKUs; 3% spare allowance",
    website: "https://example.com/yiwu-direct",
    rating: 4.0,
    verified: false,
    categories: ["gifts", "home", "beauty"],
  },
  {
    name: "Atlas Global Mix",
    warehouseLocation: "Multiple bonded warehouses",
    region: "GLOBAL",
    estimatedShippingDaysMin: 6,
    estimatedShippingDaysMax: 16,
    unitCost: 5.1,
    moq: 1,
    returnPolicy: "Region-dependent; US/EU nodes support 14-day returns",
    website: "https://example.com/atlas-global",
    rating: 4.4,
    verified: true,
    categories: ["gadgets", "home", "digital-print"],
  },
  {
    name: "Keysmith Digital",
    warehouseLocation: "Austin, TX (digital delivery)",
    region: "US",
    estimatedShippingDaysMin: 0,
    estimatedShippingDaysMax: 0,
    unitCost: 0.35,
    moq: 1,
    returnPolicy: "File re-delivery anytime; refund within 7 days if undownloaded",
    website: "https://example.com/keysmith",
    rating: 4.9,
    verified: true,
    categories: ["digital", "templates", "courses"],
  },
  {
    name: "Northloop 3PL",
    warehouseLocation: "Manchester, UK",
    region: "UK",
    estimatedShippingDaysMin: 1,
    estimatedShippingDaysMax: 3,
    unitCost: 9.2,
    moq: 1,
    returnPolicy: "Free UK returns on damaged parcels",
    website: "https://example.com/northloop",
    rating: 4.6,
    verified: true,
    categories: ["fashion", "gadgets", "gifts"],
  },
  {
    name: "Sunbelt Supply Co.",
    warehouseLocation: "Dallas, TX",
    region: "US",
    estimatedShippingDaysMin: 2,
    estimatedShippingDaysMax: 5,
    unitCost: 6.25,
    moq: 2,
    returnPolicy: "30-day returns, restocking fee 10% if opened",
    website: "https://example.com/sunbelt",
    rating: 4.4,
    verified: true,
    categories: ["fitness", "pet", "auto"],
  },
  {
    name: "Iberia Fast Lane",
    warehouseLocation: "Valencia, ES",
    region: "EU",
    estimatedShippingDaysMin: 2,
    estimatedShippingDaysMax: 5,
    unitCost: 6.7,
    moq: 5,
    returnPolicy: "EU statutory returns, prepaid label on defects",
    website: "https://example.com/iberia-fast",
    rating: 4.5,
    verified: false,
    categories: ["home", "kitchen", "lighting"],
  },
];

const REGION_SHIP: Record<WarehouseRegion, { daysMin: number; daysMax: number; base: number; perOz: number }> = {
  US: { daysMin: 2, daysMax: 5, base: 4.99, perOz: 0.16 },
  UK: { daysMin: 2, daysMax: 5, base: 5.49, perOz: 0.18 },
  EU: { daysMin: 3, daysMax: 7, base: 6.49, perOz: 0.17 },
  GLOBAL: { daysMin: 6, daysMax: 16, base: 7.25, perOz: 0.12 },
  CN: { daysMin: 12, daysMax: 25, base: 3.5, perOz: 0.08 },
};

export function estimateShipping(weightOz: number, region: WarehouseRegion) {
  const rule = REGION_SHIP[region];
  return {
    daysMin: rule.daysMin,
    daysMax: rule.daysMax,
    cost: Number((rule.base + Math.max(weightOz, 1) * rule.perOz).toFixed(2)),
  };
}

export function matchSuppliers(query: string, limit = 6): SupplierRecord[] {
  const fulfillment = inferFulfillment(query);
  const hash = hashString(query.toLowerCase());
  const scored = CATALOG_SUPPLIERS.map((supplier, index) => {
    const digitalOnly = supplier.categories.includes("digital") && supplier.estimatedShippingDaysMax === 0;
    if (fulfillment === "PHYSICAL" && digitalOnly) {
      return { supplier, score: -1 };
    }
    if (fulfillment === "DIGITAL" && !supplier.categories.includes("digital")) {
      return { supplier, score: supplier.rating };
    }
    const digitalFit = fulfillment === "DIGITAL" && supplier.categories.includes("digital") ? 30 : 0;
    const localBoost = supplier.region === "US" || supplier.region === "UK" || supplier.region === "EU" ? 8 : 0;
    const jitter = seededUnit(hash, index) * 10;
    return { supplier, score: supplier.rating * 10 + digitalFit + localBoost + jitter };
  })
    .filter((row) => row.score >= 0)
    .sort((a, b) => b.score - a.score);

  return scored.slice(0, limit).map(({ supplier }, index) => ({
    ...supplier,
    unitCost: Number((supplier.unitCost * (0.85 + seededUnit(hash, 12 + index) * 0.4)).toFixed(2)),
    moq: fulfillment === "DIGITAL" ? 1 : supplier.moq,
    estimatedShippingDaysMin:
      fulfillment === "DIGITAL" ? 0 : supplier.estimatedShippingDaysMin,
    estimatedShippingDaysMax:
      fulfillment === "DIGITAL" ? 0 : supplier.estimatedShippingDaysMax,
  }));
}

export function filterSuppliers(params: {
  region?: WarehouseRegion | "LOCAL" | "OVERSEAS" | "ALL";
  q?: string;
  maxDays?: number;
}) {
  const q = params.q?.toLowerCase().trim() ?? "";
  return CATALOG_SUPPLIERS.filter((supplier) => {
    if (params.region === "LOCAL") {
      if (!["US", "UK", "EU"].includes(supplier.region)) return false;
    } else if (params.region === "OVERSEAS") {
      if (!["CN", "GLOBAL"].includes(supplier.region)) return false;
    } else if (params.region && params.region !== "ALL" && supplier.region !== params.region) {
      return false;
    }
    if (params.maxDays && supplier.estimatedShippingDaysMax > params.maxDays) return false;
    if (!q) return true;
    const haystack = `${supplier.name} ${supplier.warehouseLocation} ${supplier.categories.join(" ")}`.toLowerCase();
    return haystack.includes(q);
  }).sort((a, b) => b.rating - a.rating);
}

export function shippingBand(region: WarehouseRegion) {
  return REGION_SHIP[region];
}

export function jitterCost(base: number, salt: number) {
  return Number((base * (0.9 + seededInt(salt, 0, 20, 3) / 100)).toFixed(2));
}

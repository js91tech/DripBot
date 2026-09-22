import { NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";
import { filterSuppliers } from "@/lib/supplier-engine";
import { parseJson } from "@/lib/format";
import type { WarehouseRegion } from "@/lib/types";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const q = searchParams.get("q") ?? undefined;
  const region = (searchParams.get("region") ?? "ALL") as
    | WarehouseRegion
    | "LOCAL"
    | "OVERSEAS"
    | "ALL";
  const maxDays = searchParams.get("maxDays");

  const stored = await prisma.supplier.findMany({ orderBy: { rating: "desc" } });
  if (stored.length) {
    const mapped = stored.map((supplier) => ({
      ...supplier,
      categories: parseJson<string[]>(supplier.categories, []),
    }));
    const filtered = mapped.filter((supplier) => {
      if (region === "LOCAL" && !["US", "UK", "EU"].includes(supplier.region)) return false;
      if (region === "OVERSEAS" && !["CN", "GLOBAL"].includes(supplier.region)) return false;
      if (region !== "ALL" && region !== "LOCAL" && region !== "OVERSEAS" && supplier.region !== region) {
        return false;
      }
      if (maxDays && supplier.estimatedShippingDaysMax > Number(maxDays)) return false;
      if (!q) return true;
      const hay = `${supplier.name} ${supplier.warehouseLocation} ${supplier.categories.join(" ")}`.toLowerCase();
      return hay.includes(q.toLowerCase());
    });
    return NextResponse.json({ suppliers: filtered, source: "database" });
  }

  return NextResponse.json({
    suppliers: filterSuppliers({ region, q, maxDays: maxDays ? Number(maxDays) : undefined }),
    source: "fallback",
  });
}

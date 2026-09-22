"use client";

import { useMemo, useState } from "react";
import { Input } from "@/components/ui/input";
import { SupplierTable } from "@/components/suppliers/supplier-table";
import type { SupplierRecord, WarehouseRegion } from "@/lib/types";

const FILTERS: { label: string; value: "ALL" | "LOCAL" | "OVERSEAS" | WarehouseRegion }[] = [
  { label: "All", value: "ALL" },
  { label: "Local US/UK/EU", value: "LOCAL" },
  { label: "Overseas", value: "OVERSEAS" },
  { label: "US", value: "US" },
  { label: "UK", value: "UK" },
  { label: "EU", value: "EU" },
  { label: "China", value: "CN" },
];

export function SupplierDirectory({ suppliers }: { suppliers: SupplierRecord[] }) {
  const [q, setQ] = useState("");
  const [region, setRegion] = useState<(typeof FILTERS)[number]["value"]>("ALL");

  const filtered = useMemo(() => {
    return suppliers.filter((supplier) => {
      if (region === "LOCAL" && !["US", "UK", "EU"].includes(supplier.region)) return false;
      if (region === "OVERSEAS" && !["CN", "GLOBAL"].includes(supplier.region)) return false;
      if (region !== "ALL" && region !== "LOCAL" && region !== "OVERSEAS" && supplier.region !== region) {
        return false;
      }
      if (!q.trim()) return true;
      const hay = `${supplier.name} ${supplier.warehouseLocation} ${supplier.categories.join(" ")}`.toLowerCase();
      return hay.includes(q.toLowerCase());
    });
  }, [q, region, suppliers]);

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <Input
          value={q}
          onChange={(event) => setQ(event.target.value)}
          placeholder="Search warehouse, supplier, or category"
          className="h-9 md:max-w-sm"
        />
        <div className="flex flex-wrap gap-1.5">
          {FILTERS.map((filter) => (
            <button
              key={filter.value}
              type="button"
              onClick={() => setRegion(filter.value)}
              className={`rounded-full border px-3 py-1 text-xs ${
                region === filter.value
                  ? "border-primary/40 bg-primary/15 text-primary"
                  : "border-border text-muted-foreground hover:text-foreground"
              }`}
            >
              {filter.label}
            </button>
          ))}
        </div>
      </div>
      <SupplierTable suppliers={filtered} />
    </div>
  );
}

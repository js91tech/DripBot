"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";

export function CatalogExport({ productIds }: { productIds: string[] }) {
  const [pending, setPending] = useState(false);

  async function exportCsv(format: "shopify" | "woocommerce") {
    if (!productIds.length) return;
    setPending(true);
    try {
      const response = await fetch("/api/export", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ productIds, format }),
      });
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `commercepulse-catalog-${format}.csv`;
      link.click();
      URL.revokeObjectURL(url);
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="flex flex-wrap gap-2">
      <Button variant="outline" disabled={pending || !productIds.length} onClick={() => void exportCsv("shopify")}>
        Export Shopify CSV
      </Button>
      <Button variant="outline" disabled={pending || !productIds.length} onClick={() => void exportCsv("woocommerce")}>
        Export WooCommerce CSV
      </Button>
    </div>
  );
}

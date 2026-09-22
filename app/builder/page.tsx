import { prisma } from "@/lib/prisma";
import { ProductBuilder } from "@/components/builder/product-builder";
import { parseJson } from "@/lib/format";
import { CATALOG_SUPPLIERS } from "@/lib/supplier-engine";
import type { SupplierRecord } from "@/lib/types";

export const dynamic = "force-dynamic";

export default async function BuilderPage() {
  const stored = await prisma.supplier.findMany({ orderBy: { rating: "desc" } });
  const suppliers: SupplierRecord[] = stored.length
    ? stored.map((supplier) => ({
        ...supplier,
        categories: parseJson<string[]>(supplier.categories, []),
      }))
    : CATALOG_SUPPLIERS;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Digital vs physical builder</h1>
        <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
          One form for both fulfillment models. Export Shopify or WooCommerce CSV, or save into the CommercePulse catalog
          with auto license keys for digital goods.
        </p>
      </div>
      <ProductBuilder suppliers={suppliers} />
    </div>
  );
}

import { prisma } from "@/lib/prisma";
import { SupplierDirectory } from "@/components/suppliers/supplier-directory";
import { parseJson } from "@/lib/format";
import { CATALOG_SUPPLIERS } from "@/lib/supplier-engine";
import type { SupplierRecord } from "@/lib/types";

export const dynamic = "force-dynamic";

export default async function SuppliersPage() {
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
        <h1 className="text-2xl font-semibold tracking-tight">Supplier directory</h1>
        <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
          Filter US / UK / EU warehouses for 2–5 day shipping against China and mixed global nodes. Includes unit cost,
          MOQ, and return policy.
        </p>
      </div>
      <SupplierDirectory suppliers={suppliers} />
    </div>
  );
}

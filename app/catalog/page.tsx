import { prisma } from "@/lib/prisma";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { LicenseButton } from "@/components/catalog/license-button";
import { CatalogExport } from "@/components/catalog/catalog-export";
import { money, parseJson } from "@/lib/format";

export const dynamic = "force-dynamic";

export default async function CatalogPage() {
  const products = await prisma.product.findMany({
    orderBy: { createdAt: "desc" },
    include: { suppliers: { include: { supplier: true } }, licenseKeys: true },
  });

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Hybrid catalog</h1>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
            Digital SKUs ship license keys instantly. Physical SKUs carry warehouse, weight, and shipping estimates.
          </p>
        </div>
        <CatalogExport productIds={products.map((product) => product.id)} />
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        {products.map((product) => (
          <Card key={product.id}>
            <CardHeader>
              <CardTitle className="flex items-start justify-between gap-3">
                <span>{product.name}</span>
                <Badge variant="secondary">{product.fulfillmentModel === "DIGITAL" ? "Digital" : "Physical"}</Badge>
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              <p className="text-muted-foreground">{product.description}</p>
              <div className="flex flex-wrap gap-2">
                {parseJson<string[]>(product.tags, []).map((tag) => (
                  <Badge key={tag} variant="outline">
                    {tag}
                  </Badge>
                ))}
              </div>
              <div className="grid grid-cols-2 gap-2 text-xs">
                <div>SKU {product.sku}</div>
                <div>List {money(product.listingPrice)}</div>
                <div>Cost {money(product.costPrice)}</div>
                {product.fulfillmentModel === "PHYSICAL" ? (
                  <div>Ship {money(product.shippingCostEst ?? 0)}</div>
                ) : (
                  <div>{product.licenseKeys.length} license keys</div>
                )}
              </div>
              {product.suppliers[0] ? (
                <p className="text-xs text-muted-foreground">
                  Sourced from {product.suppliers[0].supplier.name} · {product.suppliers[0].supplier.warehouseLocation}
                </p>
              ) : null}
              {product.fulfillmentModel === "DIGITAL" ? <LicenseButton productId={product.id} /> : null}
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}

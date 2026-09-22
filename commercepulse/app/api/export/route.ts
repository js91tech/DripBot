import { NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";
import { toShopifyCsv, toWooCommerceCsv, type ExportProduct } from "@/lib/csv-export";
import { parseJson } from "@/lib/format";

export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  const body = (await request.json()) as {
    productIds?: string[];
    format?: "shopify" | "woocommerce";
  };
  const format = body.format === "woocommerce" ? "woocommerce" : "shopify";
  if (!body.productIds?.length) {
    return NextResponse.json({ error: "productIds required" }, { status: 400 });
  }

  const products = await prisma.product.findMany({
    where: { id: { in: body.productIds } },
    include: { suppliers: { include: { supplier: true } } },
  });

  const mapped: ExportProduct[] = products.map((product) => ({
    name: product.name,
    description: product.description,
    sku: product.sku,
    category: product.category,
    tags: parseJson<string[]>(product.tags, []),
    listingPrice: product.listingPrice,
    costPrice: product.costPrice,
    fulfillmentModel: product.fulfillmentModel,
    inventoryCount: product.inventoryCount,
    weightOz: product.weightOz,
    vendor: product.suppliers[0]?.supplier.name ?? "CommercePulse",
  }));

  const csv = format === "shopify" ? toShopifyCsv(mapped) : toWooCommerceCsv(mapped);
  return new NextResponse(csv, {
    headers: {
      "Content-Type": "text/csv; charset=utf-8",
      "Content-Disposition": `attachment; filename="commercepulse-${format}.csv"`,
    },
  });
}

import { NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";
import { generateLicenseKey, skuFor } from "@/lib/license";
import { estimateShipping } from "@/lib/supplier-engine";
import { slugify, parseJson } from "@/lib/format";
import type { CatalogProductInput, WarehouseRegion } from "@/lib/types";

export const dynamic = "force-dynamic";

export async function GET() {
  const products = await prisma.product.findMany({
    orderBy: { createdAt: "desc" },
    include: { suppliers: { include: { supplier: true } }, licenseKeys: true },
  });
  return NextResponse.json({
    products: products.map((product) => ({
      ...product,
      tags: parseJson<string[]>(product.tags, []),
      licenseCount: product.licenseKeys.length,
    })),
  });
}

export async function POST(request: Request) {
  const body = (await request.json()) as CatalogProductInput;
  if (!body.name || !body.fulfillmentModel) {
    return NextResponse.json({ error: "name and fulfillmentModel are required" }, { status: 400 });
  }

  let shippingCostEst = 0;
  if (body.fulfillmentModel === "PHYSICAL") {
    const supplier = body.supplierId
      ? await prisma.supplier.findUnique({ where: { id: body.supplierId } })
      : null;
    const region = (supplier?.region ?? "US") as WarehouseRegion;
    shippingCostEst = estimateShipping(body.weightOz ?? 8, region).cost;
  }

  const product = await prisma.product.create({
    data: {
      name: body.name,
      slug: `${slugify(body.name)}-${crypto.randomUUID().slice(0, 4)}`,
      description: body.description || `${body.name} sourced via CommercePulse.`,
      category: body.category || "General",
      niche: body.niche || body.category || "General",
      fulfillmentModel: body.fulfillmentModel,
      sku: skuFor(body.fulfillmentModel, body.name),
      listingPrice: Number(body.listingPrice) || 0,
      costPrice: Number(body.costPrice) || 0,
      digitalFileUrl: body.digitalFileUrl,
      licenseKeyPrefix: body.fulfillmentModel === "DIGITAL" ? "CPDIG" : null,
      autoLicense: Boolean(body.autoLicense),
      weightOz: body.weightOz,
      shippingCostEst,
      inventoryCount:
        body.inventoryCount ?? (body.fulfillmentModel === "DIGITAL" ? 9999 : 25),
      viabilityScore: body.viabilityScore,
      tags: JSON.stringify(body.tags ?? []),
      suppliers: body.supplierId
        ? { create: { supplierId: body.supplierId, unitCost: Number(body.costPrice) || null } }
        : undefined,
    },
  });

  if (product.autoLicense) {
    await prisma.licenseKey.create({
      data: { productId: product.id, key: generateLicenseKey(product.licenseKeyPrefix ?? "CP") },
    });
  }

  return NextResponse.json({ product });
}

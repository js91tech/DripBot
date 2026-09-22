import { NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";
import { generateLicenseKey } from "@/lib/license";

export const dynamic = "force-dynamic";

export async function POST(
  _request: Request,
  context: { params: Promise<{ id: string }> }
) {
  const { id } = await context.params;
  const product = await prisma.product.findUnique({ where: { id } });
  if (!product) {
    return NextResponse.json({ error: "Product not found" }, { status: 404 });
  }
  if (product.fulfillmentModel !== "DIGITAL") {
    return NextResponse.json({ error: "License keys are only issued for digital products" }, { status: 400 });
  }
  const key = await prisma.licenseKey.create({
    data: { productId: product.id, key: generateLicenseKey(product.licenseKeyPrefix ?? "CPDIG") },
  });
  return NextResponse.json({ license: key });
}

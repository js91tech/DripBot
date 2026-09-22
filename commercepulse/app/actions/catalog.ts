"use server";

import { revalidatePath } from "next/cache";
import { prisma } from "@/lib/prisma";
import { generateLicenseKey } from "@/lib/license";

export async function issueLicense(productId: string) {
  const product = await prisma.product.findUnique({ where: { id: productId } });
  if (!product || product.fulfillmentModel !== "DIGITAL") {
    return { error: "Digital product required" };
  }
  const license = await prisma.licenseKey.create({
    data: { productId, key: generateLicenseKey(product.licenseKeyPrefix ?? "CPDIG") },
  });
  revalidatePath("/catalog");
  return { key: license.key };
}

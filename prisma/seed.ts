import "dotenv/config";
import { PrismaClient } from "@prisma/client";
import { CATALOG_SUPPLIERS } from "../lib/supplier-engine";
import { runResearch } from "../lib/research-engine";
import { serializeReport } from "../lib/report-mapper";
import { skuFor } from "../lib/license";
import { slugify } from "../lib/format";

const prisma = new PrismaClient();

const SAMPLE_QUERIES = [
  { query: "portable neck fan", category: "Travel gadgets", audience: "TikTok shoppers" },
  { query: "notion second brain templates", category: "Digital downloads", audience: "Productivity nerds" },
  { query: "galaxy projector lamp", category: "Home lighting", audience: "Apartment dwellers" },
  { query: "midjourney prompt vault", category: "AI digital packs", audience: "Content creators" },
];

const PRODUCTS = [
  {
    name: "AeroNeck Portable Fan",
    description: "Bladeless wearable neck fan with 3 speeds and USB-C charging. Built for summer UGC ads.",
    category: "Travel gadgets",
    niche: "Personal cooling",
    fulfillmentModel: "PHYSICAL" as const,
    listingPrice: 29.99,
    costPrice: 7.4,
    weightOz: 9,
    inventoryCount: 120,
    tags: ["tiktok", "summer", "travel"],
    viabilityScore: 78,
  },
  {
    name: "OrbitGlow Galaxy Projector",
    description: "Nebula projector with 13 lighting modes, remote, and timer. Strong evening-routine content angle.",
    category: "Home lighting",
    niche: "Ambient lighting",
    fulfillmentModel: "PHYSICAL" as const,
    listingPrice: 39.0,
    costPrice: 11.2,
    weightOz: 18,
    inventoryCount: 64,
    tags: ["home", "decor", "gifts"],
    viabilityScore: 71,
  },
  {
    name: "Second Brain Notion OS",
    description: "Linked databases for tasks, notes, CRM, and content calendar. Instant digital delivery with license keys.",
    category: "Digital downloads",
    niche: "Productivity",
    fulfillmentModel: "DIGITAL" as const,
    listingPrice: 27.0,
    costPrice: 0.4,
    digitalFileUrl: "https://files.commercepulse.local/second-brain.zip",
    autoLicense: true,
    tags: ["notion", "templates", "digital"],
    viabilityScore: 86,
  },
  {
    name: "Prompt Vault 2026",
    description: "1,200 image and video prompts grouped by niche, with a commercial-use license key on checkout.",
    category: "AI digital packs",
    niche: "Creator tools",
    fulfillmentModel: "DIGITAL" as const,
    listingPrice: 19.0,
    costPrice: 0.35,
    digitalFileUrl: "https://files.commercepulse.local/prompt-vault.zip",
    autoLicense: true,
    tags: ["ai", "midjourney", "digital"],
    viabilityScore: 82,
  },
  {
    name: "MagSnap Car Mount",
    description: "Magnetic phone mount with 3M pad and MagSafe-compatible plate. High repeat-purchase accessory.",
    category: "Auto gadgets",
    niche: "Phone accessories",
    fulfillmentModel: "PHYSICAL" as const,
    listingPrice: 22.5,
    costPrice: 5.6,
    weightOz: 5,
    inventoryCount: 200,
    tags: ["auto", "magnetic", "evergreen"],
    viabilityScore: 64,
  },
  {
    name: "Email Sequence Swipe File",
    description: "42 proven launches, winback, and cart-recovery emails. Delivered as Google Docs + Markdown.",
    category: "Digital downloads",
    niche: "Ecommerce ops",
    fulfillmentModel: "DIGITAL" as const,
    listingPrice: 34.0,
    costPrice: 0.5,
    digitalFileUrl: "https://files.commercepulse.local/email-swipes.zip",
    autoLicense: true,
    tags: ["email", "copy", "digital"],
    viabilityScore: 80,
  },
];

async function main() {
  await prisma.marketTrend.deleteMany();
  await prisma.researchReport.deleteMany();
  await prisma.licenseKey.deleteMany();
  await prisma.productSupplier.deleteMany();
  await prisma.product.deleteMany();
  await prisma.supplier.deleteMany();

  const suppliers = await Promise.all(
    CATALOG_SUPPLIERS.map((supplier) =>
      prisma.supplier.create({
        data: {
          name: supplier.name,
          warehouseLocation: supplier.warehouseLocation,
          region: supplier.region,
          estimatedShippingDaysMin: supplier.estimatedShippingDaysMin,
          estimatedShippingDaysMax: supplier.estimatedShippingDaysMax,
          unitCost: supplier.unitCost,
          moq: supplier.moq,
          returnPolicy: supplier.returnPolicy,
          website: supplier.website,
          rating: supplier.rating,
          verified: supplier.verified,
          categories: JSON.stringify(supplier.categories),
        },
      })
    )
  );

  const us = suppliers.find((s) => s.region === "US");
  const digital = suppliers.find((s) => s.name.includes("Keysmith"));
  const cn = suppliers.find((s) => s.region === "CN");

  for (const product of PRODUCTS) {
    const created = await prisma.product.create({
      data: {
        name: product.name,
        slug: `${slugify(product.name)}-${Math.random().toString(36).slice(2, 6)}`,
        description: product.description,
        category: product.category,
        niche: product.niche,
        fulfillmentModel: product.fulfillmentModel,
        sku: skuFor(product.fulfillmentModel, product.name),
        listingPrice: product.listingPrice,
        costPrice: product.costPrice,
        digitalFileUrl: product.digitalFileUrl,
        licenseKeyPrefix: product.fulfillmentModel === "DIGITAL" ? "CPDIG" : null,
        autoLicense: Boolean(product.autoLicense),
        weightOz: product.weightOz,
        shippingCostEst:
          product.fulfillmentModel === "PHYSICAL" ? Number((4.99 + (product.weightOz ?? 8) * 0.16).toFixed(2)) : 0,
        inventoryCount: product.inventoryCount ?? (product.fulfillmentModel === "DIGITAL" ? 9999 : 0),
        viabilityScore: product.viabilityScore,
        tags: JSON.stringify(product.tags),
      },
    });

    const link =
      product.fulfillmentModel === "DIGITAL" ? digital : product.name.includes("Galaxy") ? cn : us;
    if (link) {
      await prisma.productSupplier.create({
        data: { productId: created.id, supplierId: link.id, unitCost: product.costPrice },
      });
    }
  }

  for (const sample of SAMPLE_QUERIES) {
    const result = await runResearch(sample);
    await prisma.researchReport.create({
      data: {
        ...serializeReport(result),
        trends: {
          create: result.platforms.map((platform) => ({
            keyword: result.query,
            platform: platform.platform,
            searchVolume: platform.searchVolume,
            searchVolumeDelta: platform.searchVolumeDelta,
            socialMomentum: platform.socialMomentum,
            adActivityScore: platform.adActivityScore,
            sampleListings: JSON.stringify(platform.sampleListings),
          })),
        },
      },
    });
  }

  console.log("Seeded CommercePulse catalog, suppliers, and research reports.");
}

main()
  .catch((error) => {
    console.error(error);
    process.exit(1);
  })
  .finally(async () => {
    await prisma.$disconnect();
  });

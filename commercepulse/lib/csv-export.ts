import type { FulfillmentModel } from "@/lib/types";

export type ExportProduct = {
  name: string;
  description: string;
  sku: string;
  category: string;
  tags: string[];
  listingPrice: number;
  costPrice: number;
  fulfillmentModel: FulfillmentModel;
  inventoryCount?: number | null;
  weightOz?: number | null;
  vendor?: string;
};

function csvEscape(value: string | number) {
  const raw = String(value ?? "");
  if (/[",\n]/.test(raw)) return `"${raw.replace(/"/g, '""')}"`;
  return raw;
}

function toCsv(headers: string[], rows: Array<Array<string | number>>) {
  return [headers, ...rows].map((row) => row.map(csvEscape).join(",")).join("\n");
}

export function toShopifyCsv(products: ExportProduct[]) {
  const headers = [
    "Handle",
    "Title",
    "Body (HTML)",
    "Vendor",
    "Product Category",
    "Type",
    "Tags",
    "Published",
    "Option1 Name",
    "Option1 Value",
    "Variant SKU",
    "Variant Grams",
    "Variant Inventory Qty",
    "Variant Inventory Policy",
    "Variant Fulfillment Service",
    "Variant Price",
    "Variant Requires Shipping",
    "Variant Taxable",
    "Cost per item",
    "Status",
  ];

  const rows = products.map((product) => {
    const handle = product.name.toLowerCase().replace(/[^a-z0-9]+/g, "-");
    const grams = Math.round((product.weightOz ?? 4) * 28.3495);
    const digital = product.fulfillmentModel === "DIGITAL";
    return [
      handle,
      product.name,
      `<p>${product.description}</p>`,
      product.vendor || "CommercePulse",
      product.category,
      digital ? "Digital" : "Physical",
      product.tags.join(", "),
      "TRUE",
      "Title",
      "Default Title",
      product.sku,
      digital ? 0 : grams,
      product.inventoryCount ?? (digital ? 9999 : 25),
      "deny",
      digital ? "manual" : "manual",
      product.listingPrice.toFixed(2),
      digital ? "FALSE" : "TRUE",
      "TRUE",
      product.costPrice.toFixed(2),
      "active",
    ];
  });

  return toCsv(headers, rows);
}

export function toWooCommerceCsv(products: ExportProduct[]) {
  const headers = [
    "Type",
    "SKU",
    "Name",
    "Published",
    "Short description",
    "Description",
    "Regular price",
    "Categories",
    "Tags",
    "Weight",
    "In stock?",
    "Stock",
    "Virtual",
    "Downloadable",
  ];

  const rows = products.map((product) => {
    const digital = product.fulfillmentModel === "DIGITAL";
    const weightLb = ((product.weightOz ?? 0) / 16).toFixed(2);
    return [
      "simple",
      product.sku,
      product.name,
      1,
      product.description.slice(0, 140),
      product.description,
      product.listingPrice.toFixed(2),
      product.category,
      product.tags.join(", "),
      digital ? 0 : weightLb,
      1,
      product.inventoryCount ?? (digital ? 9999 : 25),
      digital ? 1 : 0,
      digital ? 1 : 0,
    ];
  });

  return toCsv(headers, rows);
}

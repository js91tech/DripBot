"use client";

import { useMemo, useState } from "react";
import { Download, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { estimateShipping } from "@/lib/supplier-engine";
import { money } from "@/lib/format";
import { toShopifyCsv, toWooCommerceCsv } from "@/lib/csv-export";
import type { FulfillmentModel, SupplierRecord, WarehouseRegion } from "@/lib/types";

export function ProductBuilder({ suppliers }: { suppliers: SupplierRecord[] }) {
  const [model, setModel] = useState<FulfillmentModel>("PHYSICAL");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [category, setCategory] = useState("");
  const [listingPrice, setListingPrice] = useState("29.99");
  const [costPrice, setCostPrice] = useState("7.50");
  const [weightOz, setWeightOz] = useState("8");
  const [inventoryCount, setInventoryCount] = useState("50");
  const [digitalFileUrl, setDigitalFileUrl] = useState("");
  const [autoLicense, setAutoLicense] = useState(true);
  const [supplierId, setSupplierId] = useState(suppliers[0]?.id ?? "");
  const [status, setStatus] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [savedId, setSavedId] = useState<string | null>(null);

  const supplier = suppliers.find((item) => item.id === supplierId);
  const shipping = useMemo(() => {
    if (model !== "PHYSICAL") return { cost: 0, daysMin: 0, daysMax: 0 };
    return estimateShipping(Number(weightOz) || 8, (supplier?.region ?? "US") as WarehouseRegion);
  }, [model, weightOz, supplier]);

  const preview = {
    name: name || "Untitled product",
    description: description || "Exported from CommercePulse",
    sku: model === "DIGITAL" ? "CP-DIG-PREVIEW" : "CP-PHY-PREVIEW",
    category: category || "General",
    tags: [model.toLowerCase(), category || "dropship"].filter(Boolean),
    listingPrice: Number(listingPrice) || 0,
    costPrice: Number(costPrice) || 0,
    fulfillmentModel: model,
    inventoryCount: Number(inventoryCount) || 0,
    weightOz: Number(weightOz) || 0,
  };

  async function save() {
    setPending(true);
    setStatus(null);
    try {
      const response = await fetch("/api/products", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: preview.name,
          description: preview.description,
          category: preview.category,
          niche: preview.category,
          fulfillmentModel: model,
          listingPrice: preview.listingPrice,
          costPrice: preview.costPrice,
          digitalFileUrl: model === "DIGITAL" ? digitalFileUrl : undefined,
          autoLicense: model === "DIGITAL" ? autoLicense : false,
          weightOz: model === "PHYSICAL" ? preview.weightOz : undefined,
          inventoryCount: preview.inventoryCount,
          supplierId: model === "PHYSICAL" ? supplierId || undefined : undefined,
          tags: preview.tags,
        }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Save failed");
      setSavedId(data.product.id);
      setStatus(`Saved to catalog as ${data.product.sku}`);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Save failed");
    } finally {
      setPending(false);
    }
  }

  function download(format: "shopify" | "woocommerce") {
    const csv = format === "shopify" ? toShopifyCsv([preview]) : toWooCommerceCsv([preview]);
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${preview.name.replace(/\s+/g, "-").toLowerCase()}-${format}.csv`;
    link.click();
    URL.revokeObjectURL(url);
  }

  async function exportSaved(format: "shopify" | "woocommerce") {
    if (!savedId) {
      download(format);
      return;
    }
    const response = await fetch("/api/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ productIds: [savedId], format }),
    });
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `commercepulse-${format}.csv`;
    link.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="grid gap-6 lg:grid-cols-[1.1fr_0.9fr]">
      <Card>
        <CardHeader>
          <CardTitle>Listing details</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <Tabs value={model} onValueChange={(value) => setModel(value as FulfillmentModel)}>
            <TabsList>
              <TabsTrigger value="PHYSICAL">Physical dropship</TabsTrigger>
              <TabsTrigger value="DIGITAL">Digital product</TabsTrigger>
            </TabsList>
            <TabsContent value="PHYSICAL" className="space-y-4 pt-4">
              <Field label="Product name">
                <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="AeroNeck Portable Fan" />
              </Field>
              <Field label="Description">
                <Textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={4} />
              </Field>
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="Category">
                  <Input value={category} onChange={(e) => setCategory(e.target.value)} placeholder="Travel gadgets" />
                </Field>
                <Field label="Supplier">
                  <select
                    className="h-8 w-full rounded-lg border border-input bg-transparent px-2.5 text-sm"
                    value={supplierId}
                    onChange={(e) => setSupplierId(e.target.value)}
                  >
                    {suppliers
                      .filter((item) => item.region !== "US" || true)
                      .map((item) => (
                        <option key={item.id} value={item.id} className="bg-background">
                          {item.name} · {item.warehouseLocation}
                        </option>
                      ))}
                  </select>
                </Field>
              </div>
              <div className="grid gap-3 sm:grid-cols-3">
                <Field label="List price">
                  <Input value={listingPrice} onChange={(e) => setListingPrice(e.target.value)} />
                </Field>
                <Field label="Unit cost">
                  <Input value={costPrice} onChange={(e) => setCostPrice(e.target.value)} />
                </Field>
                <Field label="Weight (oz)">
                  <Input value={weightOz} onChange={(e) => setWeightOz(e.target.value)} />
                </Field>
              </div>
              <Field label="Inventory">
                <Input value={inventoryCount} onChange={(e) => setInventoryCount(e.target.value)} />
              </Field>
            </TabsContent>
            <TabsContent value="DIGITAL" className="space-y-4 pt-4">
              <Field label="Product name">
                <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Second Brain Notion OS" />
              </Field>
              <Field label="Description">
                <Textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={4} />
              </Field>
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="Category">
                  <Input value={category} onChange={(e) => setCategory(e.target.value)} placeholder="Digital downloads" />
                </Field>
                <Field label="List price">
                  <Input value={listingPrice} onChange={(e) => setListingPrice(e.target.value)} />
                </Field>
              </div>
              <Field label="Digital file URL">
                <Input
                  value={digitalFileUrl}
                  onChange={(e) => setDigitalFileUrl(e.target.value)}
                  placeholder="https://files.yourstore.com/pack.zip"
                />
              </Field>
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={autoLicense}
                  onChange={(e) => setAutoLicense(e.target.checked)}
                />
                Auto-generate a license key on create
              </label>
            </TabsContent>
          </Tabs>
          <div className="flex flex-wrap gap-2 pt-2">
            <Button onClick={() => void save()} disabled={pending}>
              {pending ? <Loader2 className="size-4 animate-spin" /> : null}
              Save to catalog
            </Button>
            <Button variant="outline" onClick={() => void exportSaved("shopify")}>
              <Download className="size-4" />
              Shopify CSV
            </Button>
            <Button variant="outline" onClick={() => void exportSaved("woocommerce")}>
              <Download className="size-4" />
              WooCommerce CSV
            </Button>
          </div>
          {status ? <p className="text-sm text-muted-foreground">{status}</p> : null}
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Economics preview</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4 text-sm">
          <Row label="Fulfillment" value={model === "DIGITAL" ? "Instant digital" : "Physical dropship"} />
          <Row label="List price" value={money(preview.listingPrice)} />
          <Row label="Unit cost" value={money(preview.costPrice)} />
          <Row
            label="Est. shipping"
            value={model === "DIGITAL" ? "Instant" : `${money(shipping.cost)} · ${shipping.daysMin}–${shipping.daysMax} days`}
          />
          <Row
            label="Gross margin"
            value={`${Math.max(
              0,
              Math.round(
                ((preview.listingPrice - preview.costPrice - (model === "PHYSICAL" ? shipping.cost : 0)) /
                  Math.max(preview.listingPrice, 0.01)) *
                  100
              )
            )}%`}
          />
          <div className="rounded-xl bg-muted/40 p-3 font-mono text-[11px] leading-relaxed text-muted-foreground">
            {toShopifyCsv([preview]).split("\n")[0]}
            <br />
            {toShopifyCsv([preview]).split("\n")[1]?.slice(0, 180)}…
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <Label>{label}</Label>
      {children}
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-4 border-b border-border/60 py-2 last:border-0">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-medium">{value}</span>
    </div>
  );
}

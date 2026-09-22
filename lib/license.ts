import { randomBytes } from "node:crypto";

export function generateLicenseKey(prefix = "CP") {
  const body = randomBytes(8).toString("hex").toUpperCase();
  const grouped = body.match(/.{1,4}/g)?.join("-") ?? body;
  return `${prefix}-${grouped}`;
}

export function skuFor(fulfillment: "DIGITAL" | "PHYSICAL", name: string) {
  const stub = name
    .replace(/[^a-zA-Z0-9]/g, "")
    .slice(0, 6)
    .toUpperCase()
    .padEnd(4, "X");
  const n = randomBytes(2).toString("hex").toUpperCase();
  return `CP-${fulfillment === "DIGITAL" ? "DIG" : "PHY"}-${stub}-${n}`;
}

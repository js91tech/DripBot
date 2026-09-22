export type FulfillmentModel = "DIGITAL" | "PHYSICAL";
export type SaturationRisk = "LOW" | "MEDIUM" | "HIGH";
export type Verdict = "BUY" | "PASS" | "WATCH";
export type WarehouseRegion = "US" | "UK" | "EU" | "GLOBAL" | "CN";

export type Persona = {
  name: string;
  ageRange: string;
  channels: string[];
  motivation: string;
  willingnessToPay: string;
};

export type DataSource = {
  name: string;
  type: "live" | "fallback" | "llm";
  detail?: string;
};

export type PlatformTrend = {
  platform: string;
  searchVolume: number;
  searchVolumeDelta: number;
  socialMomentum: number;
  adActivityScore: number;
  sampleListings: string[];
};

export type MonthlyPoint = {
  month: string;
  demand: number;
  saturation: number;
};

export type ResearchRequest = {
  query: string;
  category?: string;
  audience?: string;
};

export type ResearchResult = {
  query: string;
  niche: string;
  category: string;
  targetAudience: string;
  viabilityScore: number;
  profitMarginPotential: number;
  competitionDensity: number;
  viralCapability: number;
  recommendedPriceMin: number;
  recommendedPriceMax: number;
  personas: Persona[];
  demandSearchVolume: number;
  demandSocialMomentum: number;
  demandAdActivity: number;
  supplyCompetitorCount: number;
  saturationRisk: SaturationRisk;
  verdict: Verdict;
  predictedMarginPct: number;
  summary: string;
  sources: DataSource[];
  monthlyTrend: MonthlyPoint[];
  platforms: PlatformTrend[];
  usedLiveData: boolean;
  usedLlm: boolean;
  fulfillmentHint: FulfillmentModel;
  unitCostEstimate: number;
};

export type SupplierRecord = {
  id?: string;
  name: string;
  warehouseLocation: string;
  region: WarehouseRegion;
  estimatedShippingDaysMin: number;
  estimatedShippingDaysMax: number;
  unitCost: number;
  moq: number;
  returnPolicy: string;
  website?: string | null;
  rating: number;
  verified: boolean;
  categories: string[];
};

export type CatalogProductInput = {
  name: string;
  description: string;
  category: string;
  niche: string;
  fulfillmentModel: FulfillmentModel;
  listingPrice: number;
  costPrice: number;
  digitalFileUrl?: string;
  autoLicense?: boolean;
  weightOz?: number;
  inventoryCount?: number;
  supplierId?: string;
  tags?: string[];
  viabilityScore?: number;
};

import { DemandAnalyzer } from "@/components/demand/demand-analyzer";

export default function DemandPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Supply & demand analyzer</h1>
        <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
          Search volume, social momentum, and ad activity versus competitor density. Every run returns a Buy / Watch /
          Pass verdict with a predicted margin.
        </p>
      </div>
      <DemandAnalyzer />
    </div>
  );
}

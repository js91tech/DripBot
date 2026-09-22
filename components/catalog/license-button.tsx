"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { issueLicense } from "@/app/actions/catalog";

export function LicenseButton({ productId }: { productId: string }) {
  const [key, setKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  return (
    <div className="space-y-1">
      <Button
        size="sm"
        variant="outline"
        onClick={async () => {
          const result = await issueLicense(productId);
          if (result.error) setError(result.error);
          else setKey(result.key ?? null);
        }}
      >
        Issue license
      </Button>
      {key ? <p className="font-mono text-[11px] text-primary">{key}</p> : null}
      {error ? <p className="text-[11px] text-destructive">{error}</p> : null}
    </div>
  );
}

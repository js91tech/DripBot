"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Loader2, Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

const SUGGESTIONS = [
  "portable neck fan",
  "notion second brain templates",
  "galaxy projector lamp",
  "midjourney prompt vault",
];

export function ResearchBar({ compact = false }: { compact?: boolean }) {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run(nextQuery = query) {
    const value = nextQuery.trim();
    if (value.length < 2) {
      setError("Enter a niche or product keyword.");
      return;
    }
    setError(null);
    setPending(true);
    try {
      const response = await fetch("/api/research", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: value }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Research failed");
      router.push(`/research/${data.id}`);
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Research failed");
    } finally {
      setPending(false);
    }
  }

  return (
    <div className={cn("w-full", compact ? "max-w-3xl" : "max-w-4xl")}>
      <form
        className="flex items-center gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          void run();
        }}
      >
        <div className="relative flex-1">
          <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Research a niche, product, or audience…"
            className="h-10 bg-card/80 pl-8"
            disabled={pending}
          />
        </div>
        <Button type="submit" disabled={pending} className="h-10 px-4">
          {pending ? <Loader2 className="size-4 animate-spin" /> : null}
          Analyze
        </Button>
      </form>
      {error ? <p className="mt-2 text-xs text-destructive">{error}</p> : null}
      {!compact ? (
        <div className="mt-3 flex flex-wrap gap-2">
          {SUGGESTIONS.map((item) => (
            <button
              key={item}
              type="button"
              onClick={() => {
                setQuery(item);
                void run(item);
              }}
              className="rounded-full border border-border bg-card/50 px-3 py-1 text-xs text-muted-foreground transition hover:border-primary/40 hover:text-foreground"
            >
              {item}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

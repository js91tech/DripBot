"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Activity,
  Boxes,
  LayoutDashboard,
  PackageSearch,
  ShoppingBag,
  Truck,
  WandSparkles,
} from "lucide-react";
import { PulseLogo } from "@/components/brand/pulse-logo";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/research", label: "Research", icon: PackageSearch },
  { href: "/demand", label: "Demand vs supply", icon: Activity },
  { href: "/suppliers", label: "Suppliers", icon: Truck },
  { href: "/catalog", label: "Catalog", icon: ShoppingBag },
  { href: "/builder", label: "Product builder", icon: WandSparkles },
];

export function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();

  return (
    <div className="flex h-full flex-col bg-sidebar text-sidebar-foreground">
      <Link href="/" onClick={onNavigate} className="flex items-center gap-2.5 px-5 py-5">
        <PulseLogo className="size-8 text-primary" />
        <div>
          <div className="text-sm font-semibold tracking-tight">CommercePulse</div>
          <div className="text-[11px] text-muted-foreground">Dropship research OS</div>
        </div>
      </Link>
      <nav className="flex flex-1 flex-col gap-0.5 px-3">
        {NAV.map((item) => {
          const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              onClick={onNavigate}
              className={cn(
                "flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm transition-colors",
                active
                  ? "bg-sidebar-accent text-sidebar-accent-foreground"
                  : "text-muted-foreground hover:bg-sidebar-accent/60 hover:text-foreground"
              )}
            >
              <Icon className="size-4" />
              {item.label}
            </Link>
          );
        })}
      </nav>
      <div className="m-3 rounded-xl border border-sidebar-border bg-background/40 p-3">
        <div className="flex items-center gap-2 text-xs font-medium">
          <Boxes className="size-3.5 text-primary" />
          Local-first demo
        </div>
        <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
          Works without API keys. Add OpenAI, Anthropic, or SerpAPI in <code>.env</code> for live enrichment.
        </p>
      </div>
    </div>
  );
}

export default function Loading() {
  return (
    <div className="space-y-4">
      <div className="h-8 w-48 animate-pulse rounded-lg bg-muted" />
      <div className="h-40 animate-pulse rounded-3xl bg-muted/60" />
      <div className="grid gap-4 md:grid-cols-3">
        <div className="h-28 animate-pulse rounded-xl bg-muted/50" />
        <div className="h-28 animate-pulse rounded-xl bg-muted/50" />
        <div className="h-28 animate-pulse rounded-xl bg-muted/50" />
      </div>
    </div>
  );
}

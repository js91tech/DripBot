import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { money, regionLabel } from "@/lib/format";
import type { SupplierRecord } from "@/lib/types";

export function SupplierTable({ suppliers }: { suppliers: SupplierRecord[] }) {
  if (!suppliers.length) {
    return (
      <p className="py-10 text-center text-sm text-muted-foreground">
        No suppliers match those filters.
      </p>
    );
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Supplier</TableHead>
          <TableHead>Warehouse</TableHead>
          <TableHead>Ship time</TableHead>
          <TableHead>Unit cost</TableHead>
          <TableHead>MOQ</TableHead>
          <TableHead>Returns</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {suppliers.map((supplier) => (
          <TableRow key={supplier.id ?? supplier.name}>
            <TableCell>
              <div className="font-medium">{supplier.name}</div>
              <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                {supplier.verified ? <Badge variant="secondary">Verified</Badge> : null}
                <span>{supplier.rating.toFixed(1)}★</span>
              </div>
            </TableCell>
            <TableCell>
              <div>{supplier.warehouseLocation}</div>
              <div className="text-xs text-muted-foreground">{regionLabel(supplier.region)}</div>
            </TableCell>
            <TableCell className="tabular-nums">
              {supplier.estimatedShippingDaysMax === 0
                ? "Instant"
                : `${supplier.estimatedShippingDaysMin}–${supplier.estimatedShippingDaysMax} days`}
            </TableCell>
            <TableCell className="tabular-nums">{money(supplier.unitCost)}</TableCell>
            <TableCell className="tabular-nums">{supplier.moq}</TableCell>
            <TableCell className="max-w-[220px] whitespace-normal text-muted-foreground">
              {supplier.returnPolicy}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

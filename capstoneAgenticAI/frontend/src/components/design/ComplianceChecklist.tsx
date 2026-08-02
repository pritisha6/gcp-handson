import { AlertTriangle, CheckCircle2, XCircle } from "lucide-react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { normalizeComplianceChecklist, type ComplianceControlRow } from "@/lib/design-adapters";
import { cn } from "@/lib/utils";
import type { DesignOutput, GuardrailResult } from "@/types/design";

export interface ComplianceChecklistProps {
  complianceChecklist: DesignOutput["compliance_checklist"];
  validationResults?: GuardrailResult[];
}

const STATUS_CONFIG: Record<ComplianceControlRow["status"], { icon: typeof CheckCircle2; label: string; className: string }> = {
  included: { icon: CheckCircle2, label: "Included", className: "text-success" },
  partial: { icon: AlertTriangle, label: "Partial", className: "text-amber-600" },
  missing: { icon: XCircle, label: "Missing", className: "text-destructive" },
};

export function ComplianceChecklist({ complianceChecklist, validationResults = [] }: ComplianceChecklistProps) {
  const rows = normalizeComplianceChecklist(complianceChecklist, validationResults);
  const missingCount = rows.filter((r) => r.status === "missing").length;

  return (
    <Card className="print:break-inside-avoid">
      <CardHeader>
        <CardTitle>Compliance Checklist</CardTitle>
        <CardDescription>
          {rows.length === 0
            ? "No regulations were specified for this design."
            : missingCount > 0
              ? `${missingCount} control${missingCount === 1 ? "" : "s"} missing — review before approval.`
              : "All required controls are accounted for."}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Regulation</TableHead>
              <TableHead>Control</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Service</TableHead>
              <TableHead>Cost</TableHead>
              <TableHead>Notes</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((row, index) => {
              const config = STATUS_CONFIG[row.status];
              const Icon = config.icon;
              return (
                <TableRow key={`${row.regulation}-${row.control}-${index}`} className={cn(row.status === "missing" && "bg-destructive/5")}>
                  <TableCell className="font-medium">{row.regulation}</TableCell>
                  <TableCell>{row.control}</TableCell>
                  <TableCell>
                    <span className={cn("flex items-center gap-1.5 text-sm", config.className)}>
                      <Icon className="h-4 w-4" aria-hidden="true" />
                      {config.label}
                    </span>
                  </TableCell>
                  <TableCell className="text-muted-foreground">{row.service ?? "—"}</TableCell>
                  <TableCell className="text-muted-foreground">{row.costEstimate ?? "—"}</TableCell>
                  <TableCell className="text-muted-foreground">{row.notes ?? "—"}</TableCell>
                </TableRow>
              );
            })}
            {rows.length === 0 && (
              <TableRow>
                <TableCell colSpan={6} className="text-center text-muted-foreground">
                  Nothing to check.
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}

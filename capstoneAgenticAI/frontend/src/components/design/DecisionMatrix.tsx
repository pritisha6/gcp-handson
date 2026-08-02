"use client";

import { Fragment, useState } from "react";
import { CheckCircle2, ChevronDown, ChevronRight, CircleDashed, XCircle } from "lucide-react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { normalizeDecisionMatrix, type DecisionMatrixRow } from "@/lib/design-adapters";
import { cn } from "@/lib/utils";
import type { DesignOutput } from "@/types/design";

export interface DecisionMatrixProps {
  decisionMatrix: DesignOutput["decision_matrix"];
}

const STATUS_CONFIG: Record<DecisionMatrixRow["status"], { icon: typeof CheckCircle2; label: string; className: string }> = {
  selected: { icon: CheckCircle2, label: "Selected", className: "text-success" },
  alternative: { icon: CircleDashed, label: "Alternative", className: "text-amber-600" },
  pruned: { icon: XCircle, label: "Pruned", className: "text-destructive" },
};

function ScoreCell({ value }: { value: number | null }) {
  if (value === null) return <span className="text-muted-foreground">&mdash;</span>;
  const pct = Math.round(value * 100);
  const color = value >= 0.8 ? "bg-success" : value >= 0.5 ? "bg-amber-500" : "bg-destructive";
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-14 overflow-hidden rounded-full bg-muted">
        <div className={cn("h-full rounded-full", color)} style={{ width: `${pct}%` }} />
      </div>
      <span className="tabular-nums text-xs text-muted-foreground">{value.toFixed(2)}</span>
    </div>
  );
}

export function DecisionMatrix({ decisionMatrix }: DecisionMatrixProps) {
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const view = normalizeDecisionMatrix(decisionMatrix);

  const toggle = (index: number) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });
  };

  return (
    <Card className="print:break-inside-avoid">
      <CardHeader>
        <CardTitle>Decision Matrix</CardTitle>
        <CardDescription>
          {view.hasDetailedScores
            ? "Services evaluated at each architecture layer, scored against latency, cost, ops, and compliance."
            : "Selected architecture path. Per-candidate score breakdowns aren't persisted by the backend yet — only the winning path and its overall score are shown."}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-6">
        <div>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-8" />
                <TableHead>Layer</TableHead>
                <TableHead>Service</TableHead>
                <TableHead>Latency</TableHead>
                <TableHead>Cost</TableHead>
                <TableHead>Ops</TableHead>
                <TableHead>Compliance</TableHead>
                <TableHead>Final</TableHead>
                <TableHead>Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {view.rows.map((row, index) => {
                const config = STATUS_CONFIG[row.status];
                const Icon = config.icon;
                const isExpanded = expanded.has(index);
                return (
                  <Fragment key={`${row.layer}-${row.service}`}>
                    <TableRow
                      className={cn(row.reasoning && "cursor-pointer")}
                      onClick={() => row.reasoning && toggle(index)}
                    >
                      <TableCell>
                        {row.reasoning && (
                          <button
                            type="button"
                            aria-label={isExpanded ? "Collapse details" : "Expand details"}
                            onClick={(e) => {
                              e.stopPropagation();
                              toggle(index);
                            }}
                          >
                            {isExpanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                          </button>
                        )}
                      </TableCell>
                      <TableCell className="capitalize text-muted-foreground">{row.layer}</TableCell>
                      <TableCell className="font-medium">{row.service}</TableCell>
                      <TableCell>
                        <ScoreCell value={row.latencyScore} />
                      </TableCell>
                      <TableCell>
                        <ScoreCell value={row.costScore} />
                      </TableCell>
                      <TableCell>
                        <ScoreCell value={row.opsScore} />
                      </TableCell>
                      <TableCell>
                        <ScoreCell value={row.complianceScore} />
                      </TableCell>
                      <TableCell className="font-semibold tabular-nums">
                        {row.finalScore !== null ? row.finalScore.toFixed(3) : "—"}
                      </TableCell>
                      <TableCell>
                        <span className={cn("flex items-center gap-1.5 text-sm", config.className)}>
                          <Icon className="h-4 w-4" aria-hidden="true" />
                          {config.label}
                        </span>
                      </TableCell>
                    </TableRow>
                    {isExpanded && row.reasoning && (
                      <TableRow>
                        <TableCell colSpan={9} className="bg-muted/30 text-sm text-muted-foreground">
                          {row.reasoning}
                        </TableCell>
                      </TableRow>
                    )}
                  </Fragment>
                );
              })}
              {view.rows.length === 0 && (
                <TableRow>
                  <TableCell colSpan={9} className="text-center text-muted-foreground">
                    No candidates to display yet.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </div>

        {view.reasoning && (
          <div className="rounded-md border bg-muted/30 p-3 text-sm">
            <span className="font-medium">Overall reasoning: </span>
            {view.reasoning}
          </div>
        )}

        {view.alternativePaths.length > 0 && (
          <div>
            <h3 className="mb-2 text-sm font-medium">Alternative complete paths considered</h3>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Path</TableHead>
                  <TableHead>Cumulative score</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {view.alternativePaths.map((alt) => (
                  <TableRow key={alt.path.join("->")}>
                    <TableCell>{alt.path.join(" → ")}</TableCell>
                    <TableCell className="tabular-nums">{alt.cumulativeScore.toFixed(3)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

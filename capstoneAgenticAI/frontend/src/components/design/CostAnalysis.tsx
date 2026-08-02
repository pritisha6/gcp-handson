"use client";

import { AlertTriangle } from "lucide-react";
import { Bar, BarChart, CartesianGrid, Cell, Legend, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { CHART_COLORS } from "@/lib/constants";
import { normalizeCostAnalysis } from "@/lib/design-adapters";
import { cn } from "@/lib/utils";
import type { DesignOutput, GuardrailResult } from "@/types/design";

export interface CostAnalysisProps {
  costAnalysis: DesignOutput["cost_analysis"];
  budgetCapUsd: number;
  currentStateCostUsd?: number;
  validationResults?: GuardrailResult[];
}

function formatUsd(amount: number): string {
  return amount.toLocaleString(undefined, { style: "currency", currency: "USD", maximumFractionDigits: 0 });
}

function extractRoiMultiplier(validationResults: GuardrailResult[]): number | null {
  for (const result of validationResults) {
    if (!result.source.includes("Cost") || !result.remediation) continue;
    const match = result.remediation.match(/ROI of ([\d.]+)x/);
    if (match) return Number(match[1]);
  }
  return null;
}

export function CostAnalysis({ costAnalysis, budgetCapUsd, currentStateCostUsd, validationResults = [] }: CostAnalysisProps) {
  const view = normalizeCostAnalysis(costAnalysis, budgetCapUsd);
  const roiMultiplier = currentStateCostUsd ? (currentStateCostUsd - view.totalUsd) / view.totalUsd : extractRoiMultiplier(validationResults);
  const businessBenefit = currentStateCostUsd ? currentStateCostUsd - view.totalUsd : null;

  const pieData = view.breakdown.map((item, index) => ({
    name: item.component,
    value: item.amount,
    fill: CHART_COLORS.categorical[index % CHART_COLORS.categorical.length],
  }));

  const budgetVsActualData = [{ name: "Monthly cost", Budget: view.budgetCapUsd, Actual: view.totalUsd }];

  return (
    <Card className="print:break-inside-avoid">
      <CardHeader>
        <CardTitle>Cost Analysis</CardTitle>
        <CardDescription>Estimated monthly cost breakdown vs. budget</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-6">
        {view.isOverBudget && (
          <div
            role="alert"
            className="flex items-center gap-2 rounded-md border border-destructive/50 bg-destructive/5 px-3 py-2 text-sm text-destructive"
          >
            <AlertTriangle className="h-4 w-4 shrink-0" aria-hidden="true" />
            Over budget by {formatUsd(view.overageUsd)} ({view.overagePct.toFixed(0)}%)
          </div>
        )}

        <div className="grid gap-6 lg:grid-cols-2">
          <div className="h-64">
            <p className="mb-2 text-sm font-medium">Cost breakdown</p>
            {pieData.length > 0 ? (
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie data={pieData} dataKey="value" nameKey="name" innerRadius={50} outerRadius={80} paddingAngle={2}>
                    {pieData.map((entry) => (
                      <Cell key={entry.name} fill={entry.fill} />
                    ))}
                  </Pie>
                  <Tooltip formatter={(value) => formatUsd(Number(value))} />
                  <Legend />
                </PieChart>
              </ResponsiveContainer>
            ) : (
              <p className="text-sm text-muted-foreground">No cost breakdown available.</p>
            )}
          </div>

          <div className="h-64">
            <p className="mb-2 text-sm font-medium">Budget cap vs. actual</p>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={budgetVsActualData}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="name" tick={{ fontSize: 12 }} />
                <YAxis tickFormatter={(v) => `$${v / 1000}K`} tick={{ fontSize: 12 }} />
                <Tooltip formatter={(value) => formatUsd(Number(value))} />
                <Legend />
                <Bar dataKey="Budget" fill={CHART_COLORS.categorical[0]} radius={[4, 4, 0, 0]} />
                <Bar
                  dataKey="Actual"
                  fill={view.isOverBudget ? CHART_COLORS.status.pruned : CHART_COLORS.status.selected}
                  radius={[4, 4, 0, 0]}
                />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="rounded-md border p-4">
          <h3 className="mb-2 text-sm font-medium">ROI analysis</h3>
          {businessBenefit !== null ? (
            <dl className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-4">
              <div>
                <dt className="text-muted-foreground">Current-system cost</dt>
                <dd className="font-medium">{formatUsd(currentStateCostUsd!)}/mo</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Design benefit</dt>
                <dd className="font-medium">{formatUsd(Math.max(0, businessBenefit))}/mo saved</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Design cost</dt>
                <dd className="font-medium">{formatUsd(view.totalUsd)}/mo</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">ROI</dt>
                <dd className="font-medium">{roiMultiplier !== null ? `${roiMultiplier.toFixed(2)}:1` : "—"}</dd>
              </div>
            </dl>
          ) : (
            <p className="text-sm text-muted-foreground">
              ROI analysis requires a current-system cost baseline, which wasn&apos;t provided for this design.
            </p>
          )}
        </div>

        <div>
          <h3 className="mb-2 text-sm font-medium">Sensitivity (approximate, client-side estimate)</h3>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Scenario</TableHead>
                <TableHead>Cost delta</TableHead>
                <TableHead>New total</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {view.sensitivity.map((row) => (
                <TableRow key={row.scenario}>
                  <TableCell>{row.scenario}</TableCell>
                  <TableCell className={cn(row.costDeltaUsd > 0 && "text-destructive")}>
                    +{formatUsd(row.costDeltaUsd)}
                  </TableCell>
                  <TableCell className="font-medium">{formatUsd(row.newTotalUsd)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>

        {view.budgetJustification && (
          <div className="rounded-md border border-amber-500/50 bg-amber-500/5 p-3 text-sm">
            <span className="font-medium">Budget justification: </span>
            {view.budgetJustification}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

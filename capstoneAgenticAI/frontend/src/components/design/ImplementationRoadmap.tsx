"use client";

import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { CHART_COLORS } from "@/lib/constants";
import { normalizeRoadmap, type RoadmapPhaseView } from "@/lib/design-adapters";
import { cn } from "@/lib/utils";
import type { DesignOutput } from "@/types/design";

export interface ImplementationRoadmapProps {
  roadmap: DesignOutput["implementation_roadmap"];
}

/** Longest-duration chain through the dependency graph, ending at whichever
 * phase finishes latest — the sequence that determines the overall timeline.
 */
function computeCriticalPath(phases: RoadmapPhaseView[]): Set<number> {
  const byNumber = new Map(phases.map((p) => [p.phase, p]));
  const chainLength = new Map<number, number>();
  const chainPrev = new Map<number, number | null>();

  function chainFor(phaseNum: number): number {
    if (chainLength.has(phaseNum)) return chainLength.get(phaseNum)!;
    const phase = byNumber.get(phaseNum);
    if (!phase) return 0;
    let best = 0;
    let bestPrev: number | null = null;
    for (const dep of phase.dependsOn) {
      const depLength = chainFor(dep);
      if (depLength > best) {
        best = depLength;
        bestPrev = dep;
      }
    }
    const total = best + phase.durationWeeks;
    chainLength.set(phaseNum, total);
    chainPrev.set(phaseNum, bestPrev);
    return total;
  }

  phases.forEach((p) => chainFor(p.phase));

  let endPhase: number | null = null;
  let maxLength = -1;
  chainLength.forEach((length, phaseNum) => {
    if (length > maxLength) {
      maxLength = length;
      endPhase = phaseNum;
    }
  });

  const critical = new Set<number>();
  let current: number | null = endPhase;
  while (current !== null) {
    critical.add(current);
    current = chainPrev.get(current) ?? null;
  }
  return critical;
}

export function ImplementationRoadmap({ roadmap }: ImplementationRoadmapProps) {
  const phases = normalizeRoadmap(roadmap);
  const criticalPath = computeCriticalPath(phases);
  const hasEstimatedTiming = phases.some((p) => p.isEstimated);

  const chartData = phases.map((phase) => ({
    name: `${phase.phase}. ${phase.name}`,
    offset: phase.startWeek - 1,
    duration: phase.durationWeeks,
    isCritical: criticalPath.has(phase.phase),
    weekRange: `Week ${phase.startWeek}${phase.durationWeeks > 1 ? `-${phase.endWeek}` : ""}`,
  }));

  return (
    <Card className="print:break-inside-avoid">
      <CardHeader>
        <CardTitle>Implementation Roadmap</CardTitle>
        <CardDescription>
          Phased rollout timeline{hasEstimatedTiming ? " (weeks marked * are estimated defaults)" : ""}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-6">
        {chartData.length > 0 ? (
          <div style={{ height: Math.max(180, chartData.length * 56) }}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={chartData} layout="vertical" margin={{ left: 24 }}>
                <CartesianGrid strokeDasharray="3 3" horizontal={false} />
                <XAxis type="number" tickFormatter={(v) => `Wk ${v + 1}`} tick={{ fontSize: 12 }} />
                <YAxis type="category" dataKey="name" width={160} tick={{ fontSize: 12 }} />
                <Tooltip
                  formatter={(value, name) => (name === "duration" ? [`${value} week(s)`, "Duration"] : [value, name])}
                  labelFormatter={(_label, payload) => payload?.[0]?.payload?.weekRange ?? ""}
                />
                <Bar dataKey="offset" stackId="gantt" fill="transparent" isAnimationActive={false} />
                <Bar dataKey="duration" stackId="gantt" radius={[4, 4, 4, 4]} isAnimationActive={false}>
                  {chartData.map((entry) => (
                    <Cell
                      key={entry.name}
                      fill={entry.isCritical ? CHART_COLORS.status.pruned : CHART_COLORS.categorical[0]}
                    />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">No roadmap phases available yet.</p>
        )}

        <div className="flex flex-wrap items-center gap-4 text-xs text-muted-foreground">
          <span className="flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-sm" style={{ backgroundColor: CHART_COLORS.status.pruned }} />
            Critical path
          </span>
          <span className="flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-sm" style={{ backgroundColor: CHART_COLORS.categorical[0] }} />
            Non-critical
          </span>
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          {phases.map((phase) => (
            <div key={phase.phase} className={cn("rounded-md border p-3", criticalPath.has(phase.phase) && "border-destructive/50")}>
              <div className="flex items-center justify-between gap-2">
                <span className="font-medium">
                  Phase {phase.phase}: {phase.name}
                </span>
                {criticalPath.has(phase.phase) && (
                  <Badge variant="destructive" className="text-[10px]">
                    Critical
                  </Badge>
                )}
              </div>
              <p className="mt-1 text-xs text-muted-foreground">
                Week {phase.startWeek}
                {phase.durationWeeks > 1 ? `-${phase.endWeek}` : ""}
                {phase.isEstimated ? " (estimated)" : ""}
              </p>
              {phase.service && <p className="mt-1 text-xs text-muted-foreground">Service: {phase.service}</p>}
              {phase.dependsOn.length > 0 && (
                <p className="mt-1 text-xs text-muted-foreground">Depends on: Phase {phase.dependsOn.join(", ")}</p>
              )}
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

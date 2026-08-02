"use client";

import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { CHART_COLORS } from "@/lib/constants";
import { cn } from "@/lib/utils";
import type { MetricsSnapshot } from "@/types/design";

export interface MetricsDashboardProps {
  metrics: MetricsSnapshot | null;
}

interface StatTile {
  label: string;
  value: string;
}

function StatGroup({ title, tiles }: { title: string; tiles: StatTile[] }) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">{title}</CardTitle>
      </CardHeader>
      <CardContent className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        {tiles.map((tile) => (
          <div key={tile.label}>
            <p className="text-2xl font-semibold tabular-nums">{tile.value}</p>
            <p className="text-xs text-muted-foreground">{tile.label}</p>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

function binHistogram(values: number[], bucketCount = 8): { bucket: string; count: number }[] {
  if (values.length === 0) return [];
  const min = Math.min(...values);
  const max = Math.max(...values);
  const width = (max - min || 1) / bucketCount;
  const buckets = Array.from({ length: bucketCount }, (_, i) => ({
    lower: min + i * width,
    upper: min + (i + 1) * width,
    count: 0,
  }));

  values.forEach((value) => {
    const index = Math.min(bucketCount - 1, Math.floor((value - min) / width));
    const bucket = buckets[index];
    if (bucket) bucket.count += 1;
  });

  return buckets.map((b) => ({ bucket: `${b.lower.toFixed(0)}-${b.upper.toFixed(0)}%`, count: b.count }));
}

function percentile(sorted: number[], p: number): number {
  if (sorted.length === 0) return 0;
  const index = (p / 100) * (sorted.length - 1);
  const lower = Math.floor(index);
  const upper = Math.ceil(index);
  const first = sorted[lower] ?? 0;
  if (lower === upper) return first;
  const second = sorted[upper] ?? first;
  return first + (second - first) * (index - lower);
}

/** Recharts has no first-class box-plot mark, so this renders a small
 * hand-built SVG box-and-whisker plot from percentiles computed client-side. */
function GenerationTimeBoxPlot({ samples }: { samples: number[] }) {
  if (samples.length === 0) {
    return <p className="flex h-full items-center justify-center text-sm text-muted-foreground">No generation time samples yet.</p>;
  }

  const sorted = [...samples].sort((a, b) => a - b);
  const min = sorted[0] ?? 0;
  const max = sorted[sorted.length - 1] ?? 0;
  const q1 = percentile(sorted, 25);
  const median = percentile(sorted, 50);
  const q3 = percentile(sorted, 75);

  const width = 480;
  const height = 100;
  const midY = height / 2;
  const scale = (v: number) => 48 + ((v - min) / (max - min || 1)) * (width - 96);
  const color = CHART_COLORS.categorical[0];

  return (
    <div className="flex h-full flex-col items-center justify-center gap-2">
      <svg viewBox={`0 0 ${width} ${height}`} className="w-full max-w-lg" role="img" aria-label="Generation time distribution box plot">
        <line x1={scale(min)} x2={scale(max)} y1={midY} y2={midY} stroke="currentColor" className="text-muted-foreground" strokeWidth={1} />
        <line x1={scale(min)} x2={scale(min)} y1={midY - 12} y2={midY + 12} stroke="currentColor" className="text-muted-foreground" strokeWidth={1} />
        <line x1={scale(max)} x2={scale(max)} y1={midY - 12} y2={midY + 12} stroke="currentColor" className="text-muted-foreground" strokeWidth={1} />
        <rect
          x={scale(q1)}
          y={midY - 20}
          width={Math.max(2, scale(q3) - scale(q1))}
          height={40}
          fill={color}
          fillOpacity={0.25}
          stroke={color}
          strokeWidth={1.5}
        />
        <line x1={scale(median)} x2={scale(median)} y1={midY - 20} y2={midY + 20} stroke={color} strokeWidth={2.5} />
        <text x={scale(min)} y={midY + 34} textAnchor="middle" className="fill-muted-foreground text-[10px]">
          {min.toFixed(1)}
        </text>
        <text x={scale(median)} y={midY - 28} textAnchor="middle" className="fill-foreground text-[10px] font-medium">
          {median.toFixed(1)}
        </text>
        <text x={scale(max)} y={midY + 34} textAnchor="middle" className="fill-muted-foreground text-[10px]">
          {max.toFixed(1)}
        </text>
      </svg>
      <p className="text-xs text-muted-foreground">
        min {min.toFixed(1)} &middot; p25 {q1.toFixed(1)} &middot; median {median.toFixed(1)} &middot; p75 {q3.toFixed(1)} &middot; max{" "}
        {max.toFixed(1)} (minutes, n={samples.length})
      </p>
    </div>
  );
}

export function MetricsDashboard({ metrics }: MetricsDashboardProps) {
  if (!metrics) {
    return (
      <Card>
        <CardContent className="py-10 text-center text-sm text-muted-foreground">
          No metrics are available yet. This dashboard populates once designs have been generated.
        </CardContent>
      </Card>
    );
  }

  const histogramData = binHistogram(metrics.cost_accuracy_distribution);

  return (
    <div className="flex flex-col gap-6">
      <div className="grid gap-4 md:grid-cols-2">
        <StatGroup
          title="Design Quality"
          tiles={[
            { label: "Coverage", value: `${metrics.quality.requirement_coverage_pct.toFixed(1)}%` },
            { label: "Accuracy", value: `${metrics.quality.accuracy_pct.toFixed(1)}%` },
            { label: "Scalability", value: `${metrics.quality.scalability_score.toFixed(1)}%` },
          ]}
        />
        <StatGroup
          title="Reliability"
          tiles={[
            { label: "Approval rate", value: `${metrics.reliability.approval_rate_pct.toFixed(1)}%` },
            { label: "Consistency", value: `${metrics.reliability.consistency_pct.toFixed(1)}%` },
            { label: "Hallucination rate", value: `${metrics.reliability.hallucination_rate_pct.toFixed(1)}%` },
          ]}
        />
        <StatGroup
          title="Efficiency"
          tiles={[
            { label: "Generation time", value: `${metrics.efficiency.avg_generation_time_minutes.toFixed(1)} min` },
            { label: "API calls", value: metrics.efficiency.avg_api_calls.toFixed(1) },
            { label: "API cost", value: `$${metrics.efficiency.avg_api_cost_usd.toFixed(3)}` },
          ]}
        />
        <StatGroup
          title="User Impact"
          tiles={[
            { label: "Satisfaction", value: `${metrics.user_impact.satisfaction_score.toFixed(1)}/5.0` },
            { label: "Time saved / project", value: `${metrics.user_impact.avg_time_saved_hours.toFixed(1)} hrs` },
            { label: "Business value", value: `$${metrics.user_impact.business_value_usd.toLocaleString()}` },
          ]}
        />
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Coverage trend</CardTitle>
            <CardDescription>Last 30 days</CardDescription>
          </CardHeader>
          <CardContent className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={metrics.coverage_trend}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="date" tick={{ fontSize: 11 }} />
                <YAxis tickFormatter={(v) => `${v}%`} tick={{ fontSize: 12 }} domain={[0, 100]} />
                <Tooltip formatter={(value) => `${value}%`} />
                <Line type="monotone" dataKey="value" stroke={CHART_COLORS.categorical[0]} strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Approval rate by stakeholder</CardTitle>
          </CardHeader>
          <CardContent className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={metrics.approval_rate_by_stakeholder}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="role" tick={{ fontSize: 12 }} className="capitalize" />
                <YAxis tickFormatter={(v) => `${v}%`} tick={{ fontSize: 12 }} domain={[0, 100]} />
                <Tooltip formatter={(value) => `${value}%`} />
                <Bar dataKey="approval_rate_pct" fill={CHART_COLORS.categorical[1]} radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Accuracy score distribution</CardTitle>
            <CardDescription>Guardrail pass rate, across all designs</CardDescription>
          </CardHeader>
          <CardContent className={cn("h-64", histogramData.length === 0 && "flex items-center justify-center")}>
            {histogramData.length > 0 ? (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={histogramData}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="bucket" tick={{ fontSize: 11 }} />
                  <YAxis allowDecimals={false} tick={{ fontSize: 12 }} />
                  <Tooltip />
                  <Bar dataKey="count" fill={CHART_COLORS.categorical[2]} radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <p className="text-sm text-muted-foreground">No distribution data available.</p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Generation time percentiles</CardTitle>
            <CardDescription>Distribution of end-to-end design generation time</CardDescription>
          </CardHeader>
          <CardContent className="h-64">
            <GenerationTimeBoxPlot samples={metrics.generation_time_minutes_samples} />
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

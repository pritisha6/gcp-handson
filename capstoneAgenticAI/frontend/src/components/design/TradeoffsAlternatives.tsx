import { Award, TrendingDown } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { normalizeDecisionMatrix } from "@/lib/design-adapters";
import { cn } from "@/lib/utils";
import type { DesignOutput } from "@/types/design";

export interface TradeoffsAlternativesProps {
  decisionMatrix: DesignOutput["decision_matrix"];
}

function recommendationFor(scoreDelta: number): { label: string; tone: "neutral" | "caution" } {
  if (scoreDelta >= -0.05) return { label: "Close alternative — reasonable fallback", tone: "neutral" };
  if (scoreDelta >= -0.2) return { label: "Viable if primary constraints change", tone: "caution" };
  return { label: "Not recommended under current requirements", tone: "caution" };
}

export function TradeoffsAlternatives({ decisionMatrix }: TradeoffsAlternativesProps) {
  const view = normalizeDecisionMatrix(decisionMatrix);

  return (
    <Card className="print:break-inside-avoid">
      <CardHeader>
        <CardTitle>Trade-offs &amp; Alternatives</CardTitle>
        <CardDescription>How the selected architecture compares to other paths the search considered</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {view.selectedPath.length > 0 && (
          <div className="rounded-md border-2 border-success/50 bg-success/5 p-4">
            <div className="flex items-center gap-2">
              <Award className="h-4 w-4 text-success" aria-hidden="true" />
              <span className="text-sm font-semibold">Primary recommendation</span>
            </div>
            <p className="mt-1 text-base font-medium">{view.selectedPath.join(" + ")}</p>
            {view.finalScore !== null && (
              <p className="mt-1 text-sm text-muted-foreground">Overall score: {view.finalScore.toFixed(3)}</p>
            )}
            {view.reasoning && <p className="mt-2 text-sm text-muted-foreground">{view.reasoning}</p>}
          </div>
        )}

        {view.alternativePaths.length > 0 ? (
          <div className="grid gap-3 sm:grid-cols-2">
            {view.alternativePaths.map((alt, index) => {
              const scoreDelta = view.finalScore !== null ? alt.cumulativeScore - view.finalScore : 0;
              const recommendation = recommendationFor(scoreDelta);
              return (
                <div key={alt.path.join("->")} className="rounded-md border p-4">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-sm font-semibold">Alternative {index + 1}</span>
                    <Badge variant={recommendation.tone === "caution" ? "secondary" : "outline"} className="gap-1 text-[10px]">
                      <TrendingDown className="h-3 w-3" aria-hidden="true" />
                      {scoreDelta >= 0 ? "+" : ""}
                      {scoreDelta.toFixed(3)} vs. primary
                    </Badge>
                  </div>
                  <p className="mt-1 font-medium">{alt.path.join(" + ")}</p>
                  <p className="mt-1 text-sm text-muted-foreground">Score: {alt.cumulativeScore.toFixed(3)}</p>
                  <p className={cn("mt-2 text-sm", recommendation.tone === "caution" ? "text-amber-600" : "text-muted-foreground")}>
                    {recommendation.label}
                  </p>
                </div>
              );
            })}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">
            No alternative architectures were recorded for this design.
          </p>
        )}
      </CardContent>
    </Card>
  );
}

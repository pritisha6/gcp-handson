import { AlertTriangle, ShieldCheck } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import type { Alert } from "@/types/design";

export interface AlertsWidgetProps {
  alerts: Alert[];
}

/** Dashboard widget showing currently active threshold-crossing alerts. */
export function AlertsWidget({ alerts }: AlertsWidgetProps) {
  if (alerts.length === 0) {
    return (
      <Card className="border-success/50 bg-success/5">
        <CardContent className="flex items-center gap-2 py-4 text-sm text-success">
          <ShieldCheck className="h-4 w-4" aria-hidden="true" />
          No active alerts — all metrics are within their configured thresholds.
        </CardContent>
      </Card>
    );
  }

  const hasCritical = alerts.some((a) => a.severity === "CRITICAL");

  return (
    <Card className={cn(hasCritical ? "border-destructive/50 bg-destructive/5" : "border-amber-500/50 bg-amber-500/5")}>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-base">
          <AlertTriangle className="h-4 w-4" aria-hidden="true" />
          {alerts.length} active alert{alerts.length === 1 ? "" : "s"}
        </CardTitle>
        <CardDescription>Metrics currently outside their configured thresholds</CardDescription>
      </CardHeader>
      <CardContent>
        <ul className="flex flex-col gap-2">
          {alerts.map((alert) => (
            <li key={`${alert.metric}-${alert.triggered_at}`} className="flex flex-wrap items-center gap-2 text-sm">
              <Badge variant={alert.severity === "CRITICAL" ? "destructive" : "secondary"} className="text-[10px]">
                {alert.severity}
              </Badge>
              <span>{alert.message}</span>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

import { AlertTriangle, CheckCircle2, OctagonX, ShieldAlert } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { GuardrailStatusValue } from "@/types/design";

const STATUS_CONFIG: Record<
  GuardrailStatusValue,
  { label: string; icon: typeof CheckCircle2; className: string }
> = {
  PASS: { label: "Pass", icon: CheckCircle2, className: "border-transparent bg-success text-success-foreground" },
  FLAG: { label: "Flagged", icon: AlertTriangle, className: "border-transparent bg-amber-500 text-white" },
  ESCALATE: { label: "Escalated", icon: ShieldAlert, className: "border-transparent bg-orange-600 text-white" },
  STOP: { label: "Blocked", icon: OctagonX, className: "border-transparent bg-destructive text-destructive-foreground" },
};

export interface GuardrailBadgeProps {
  status: GuardrailStatusValue;
  className?: string;
  showIcon?: boolean;
}

export function GuardrailBadge({ status, className, showIcon = true }: GuardrailBadgeProps) {
  const config = STATUS_CONFIG[status];
  const Icon = config.icon;
  return (
    <Badge className={cn("gap-1", config.className, className)}>
      {showIcon && <Icon className="h-3 w-3" aria-hidden="true" />}
      {config.label}
    </Badge>
  );
}

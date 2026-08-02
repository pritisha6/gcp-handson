import { format } from "date-fns";
import { CheckCircle2, Circle, XCircle } from "lucide-react";

import { APPROVAL_ROLE_LABELS } from "@/lib/constants";
import { cn } from "@/lib/utils";
import { APPROVAL_ROLES, type Approval } from "@/types/design";

export interface AuditTrailProps {
  approval: Approval | null;
}

const DECISION_CONFIG = {
  approved: { icon: CheckCircle2, className: "text-success", label: "Approved" },
  rejected: { icon: XCircle, className: "text-destructive", label: "Rejected / Needs revision" },
  pending: { icon: Circle, className: "text-muted-foreground", label: "Pending" },
} as const;

/** Timeline of every stakeholder's approval decision, format: [Time] [Role] [Decision] [Comment]. */
export function AuditTrail({ approval }: AuditTrailProps) {
  const entries = APPROVAL_ROLES.map((role) => ({
    role,
    entry: approval?.approvals[role] ?? { decision: "pending" as const, comment: null, decided_at: null },
  }));

  const sorted = [...entries].sort((a, b) => {
    if (!a.entry.decided_at && !b.entry.decided_at) return 0;
    if (!a.entry.decided_at) return 1;
    if (!b.entry.decided_at) return -1;
    return new Date(a.entry.decided_at).getTime() - new Date(b.entry.decided_at).getTime();
  });

  return (
    <div className="flex flex-col gap-4">
      <h3 className="text-sm font-medium">Approval timeline</h3>
      <ol className="flex flex-col gap-4 border-l pl-4">
        {sorted.map(({ role, entry }) => {
          const config = DECISION_CONFIG[entry.decision];
          const Icon = config.icon;
          return (
            <li key={role} className="relative">
              <span
                className={cn(
                  "absolute -left-[21px] flex h-3 w-3 items-center justify-center rounded-full bg-background",
                  config.className
                )}
              >
                <Icon className="h-3 w-3" aria-hidden="true" />
              </span>
              <div className="flex flex-wrap items-baseline gap-2">
                <span className="text-sm font-medium">{APPROVAL_ROLE_LABELS[role] ?? role}</span>
                <span className={cn("text-xs font-medium", config.className)}>{config.label}</span>
                {entry.decided_at && (
                  <span className="text-xs text-muted-foreground">
                    {format(new Date(entry.decided_at), "MMM d, yyyy h:mm a")}
                  </span>
                )}
              </div>
              {entry.comment && <p className="mt-1 text-sm text-muted-foreground">&ldquo;{entry.comment}&rdquo;</p>}
            </li>
          );
        })}
      </ol>
    </div>
  );
}

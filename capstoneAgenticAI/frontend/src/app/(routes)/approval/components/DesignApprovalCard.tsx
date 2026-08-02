"use client";

import { useEffect, useRef } from "react";
import Link from "next/link";
import { AlertCircle, ExternalLink, Wifi, WifiOff } from "lucide-react";

import { ApprovalForm } from "@/components/approval/ApprovalForm";
import { AuditTrail } from "@/components/approval/AuditTrail";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useApprovalStatus } from "@/hooks/useApprovalStatus";
import { APPROVAL_ROLE_LABELS } from "@/lib/constants";
import { cn } from "@/lib/utils";
import { APPROVAL_ROLES, type Design } from "@/types/design";

export interface DesignApprovalCardProps {
  design: Design;
  highlighted?: boolean;
}

export function DesignApprovalCard({ design, highlighted = false }: DesignApprovalCardProps) {
  const { approval, isLive, refresh } = useApprovalStatus(design.id);
  const cardRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (highlighted) {
      cardRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, [highlighted]);

  const totalCost = design.output?.cost_analysis?.total_usd;
  const selectedPath = design.output?.decision_matrix?.selected_path ?? [];
  const pendingRoles = APPROVAL_ROLES.filter(
    (role) => (approval?.approvals[role]?.decision ?? "pending") === "pending"
  );

  return (
    <Card id={design.id} ref={cardRef} className={cn(highlighted && "border-primary ring-2 ring-primary/30")}>
      <CardHeader className="flex flex-row flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <CardTitle className="text-lg">{design.project_name}</CardTitle>
            <Badge variant="secondary" className="capitalize">
              {design.status.replace("_", " ")}
            </Badge>
          </div>
          <CardDescription>
            {selectedPath.length > 0 ? selectedPath.join(" → ") : "Architecture pending"}
            {totalCost !== undefined && ` · $${totalCost.toLocaleString()}/mo`}
          </CardDescription>
        </div>
        <div className="flex items-center gap-3">
          <span className="flex items-center gap-1 text-xs text-muted-foreground" title={isLive ? "Live updates" : "Polling for updates"}>
            {isLive ? <Wifi className="h-3 w-3" /> : <WifiOff className="h-3 w-3" />}
            {isLive ? "Live" : "Polling"}
          </span>
          <Button asChild variant="outline" size="sm">
            <Link href={`/design/${design.id}`}>
              <ExternalLink className="h-4 w-4" />
              View design
            </Link>
          </Button>
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-6">
        {pendingRoles.length > 0 && (
          <div className="flex flex-wrap items-center gap-1.5 text-sm">
            <AlertCircle className="h-4 w-4 text-destructive" aria-hidden="true" />
            <span className="text-muted-foreground">Awaiting:</span>
            {pendingRoles.map((role) => (
              <Badge key={role} variant="destructive" className="text-[10px]">
                {APPROVAL_ROLE_LABELS[role]}
              </Badge>
            ))}
          </div>
        )}

        <div className="grid gap-6 lg:grid-cols-2">
          <AuditTrail approval={approval} />
          <ApprovalForm design={design} onSubmitted={() => refresh()} />
        </div>
      </CardContent>
    </Card>
  );
}

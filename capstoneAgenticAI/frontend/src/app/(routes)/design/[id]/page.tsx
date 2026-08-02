"use client";

import { useEffect, useRef } from "react";
import Link from "next/link";
import { AlertTriangle, CheckCircle2, FileDown, Image as ImageIcon, XCircle } from "lucide-react";

import { ArchitectureDiagram, type ArchitectureDiagramHandle } from "@/components/design/ArchitectureDiagram";
import { ComplianceChecklist } from "@/components/design/ComplianceChecklist";
import { CostAnalysis } from "@/components/design/CostAnalysis";
import { DecisionMatrix } from "@/components/design/DecisionMatrix";
import { ImplementationRoadmap } from "@/components/design/ImplementationRoadmap";
import { TradeoffsAlternatives } from "@/components/design/TradeoffsAlternatives";
import { GuardrailBadge } from "@/components/shared/GuardrailBadge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useApi } from "@/hooks/useApi";
import { apiClient } from "@/lib/api";
import type { DesignStatus } from "@/types/design";

const STATUS_BADGE: Record<DesignStatus, { label: string; className: string }> = {
  pending: { label: "Pending", className: "bg-secondary text-secondary-foreground" },
  in_progress: { label: "In progress", className: "bg-amber-500 text-white" },
  completed: { label: "Completed", className: "bg-success text-success-foreground" },
  failed: { label: "Failed", className: "bg-destructive text-destructive-foreground" },
  deleted: { label: "Deleted", className: "bg-muted text-muted-foreground" },
};

function DesignDetailSkeleton() {
  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-6">
      <Skeleton className="h-9 w-2/3" />
      <Skeleton className="h-5 w-1/3" />
      <Skeleton className="h-96 w-full" />
      <Skeleton className="h-64 w-full" />
      <Skeleton className="h-64 w-full" />
    </div>
  );
}

export default function DesignDetailPage({ params }: { params: { id: string } }) {
  const { data: design, loading, error, execute } = useApi((id: string) => apiClient.getDesign(id));
  const diagramRef = useRef<ArchitectureDiagramHandle>(null);

  useEffect(() => {
    execute(params.id).catch(() => {
      // error state is already surfaced via useApi's `error`
    });
  }, [execute, params.id]);

  if (loading || (!design && !error)) {
    return <DesignDetailSkeleton />;
  }

  if (error || !design) {
    return (
      <div className="mx-auto flex max-w-lg flex-col items-center gap-3 py-16 text-center">
        <XCircle className="h-10 w-10 text-destructive" aria-hidden="true" />
        <h1 className="text-lg font-semibold">Design not found</h1>
        <p className="text-sm text-muted-foreground">{error ?? "This design could not be loaded."}</p>
        <Button asChild variant="outline" className="mt-2">
          <Link href="/history">Back to history</Link>
        </Button>
      </div>
    );
  }

  const statusBadge = STATUS_BADGE[design.status];
  const blockingResults = design.validation_results.filter((r) => r.status === "ESCALATE" || r.status === "STOP");

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-6">
      <div className="flex flex-col gap-3 border-b pb-4 print:border-none">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-2xl font-bold tracking-tight">{design.project_name}</h1>
              <Badge className={statusBadge.className}>{statusBadge.label}</Badge>
            </div>
            <p className="mt-1 text-sm text-muted-foreground">
              Design ID: <span className="font-mono">{design.id}</span> &middot; Updated{" "}
              {new Date(design.updated_at).toLocaleString()}
            </p>
          </div>
          <div className="flex flex-wrap gap-2 print:hidden">
            <Button variant="outline" onClick={() => window.print()}>
              <FileDown className="h-4 w-4" />
              Download PDF
            </Button>
            <Button variant="outline" onClick={() => diagramRef.current?.downloadPng()}>
              <ImageIcon className="h-4 w-4" />
              Download Architecture
            </Button>
            <Button asChild>
              <Link href={`/approval?designId=${encodeURIComponent(design.id)}#${design.id}`}>
                <CheckCircle2 className="h-4 w-4" />
                Approve
              </Link>
            </Button>
            <Button asChild variant="secondary">
              <Link href={`/approval?designId=${encodeURIComponent(design.id)}&action=revise#${design.id}`}>
                <AlertTriangle className="h-4 w-4" />
                Request Revision
              </Link>
            </Button>
          </div>
        </div>

        {blockingResults.length > 0 && (
          <Card className="border-amber-500/50 bg-amber-500/5">
            <CardContent className="flex flex-col gap-2 py-3">
              <p className="text-sm font-medium">{blockingResults.length} guardrail result(s) need attention</p>
              <ul className="flex flex-col gap-1.5">
                {blockingResults.map((result, index) => (
                  <li key={index} className="flex flex-wrap items-center gap-2 text-sm">
                    <GuardrailBadge status={result.status} />
                    <span className="text-muted-foreground">{result.source}:</span>
                    {result.message}
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>
        )}
      </div>

      <ArchitectureDiagram ref={diagramRef} design={design} />
      <DecisionMatrix decisionMatrix={design.output?.decision_matrix} />
      <CostAnalysis
        costAnalysis={design.output?.cost_analysis}
        budgetCapUsd={design.requirements.budget.monthly_cap_usd}
        validationResults={design.validation_results}
      />
      <ComplianceChecklist
        complianceChecklist={design.output?.compliance_checklist}
        validationResults={design.validation_results}
      />
      <ImplementationRoadmap roadmap={design.output?.implementation_roadmap} />
      <TradeoffsAlternatives decisionMatrix={design.output?.decision_matrix} />
    </div>
  );
}

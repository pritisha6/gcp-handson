"use client";

import { Suspense, useEffect } from "react";
import { useSearchParams } from "next/navigation";

import { DesignApprovalCard } from "@/app/(routes)/approval/components/DesignApprovalCard";
import { LoadingSpinner } from "@/components/shared/LoadingSpinner";
import { useApi } from "@/hooks/useApi";
import { apiClient } from "@/lib/api";

function ApprovalPageContent() {
  const { data, loading, error, execute } = useApi(() => apiClient.listDesigns({ status: "completed", limit: 50 }));
  const searchParams = useSearchParams();
  const highlightId = searchParams.get("designId");

  useEffect(() => {
    execute().catch(() => {
      // error state is already surfaced via useApi's `error`
    });
  }, [execute]);

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Pending Approvals</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Designs awaiting sign-off from engineering, architecture, CFO, security, and ops.
        </p>
      </div>

      {loading && (
        <div className="flex justify-center py-16">
          <LoadingSpinner label="Loading designs..." />
        </div>
      )}

      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}

      {!loading && !error && data?.items.length === 0 && (
        <p className="text-sm text-muted-foreground">No designs are currently awaiting approval.</p>
      )}

      <div className="flex flex-col gap-6">
        {data?.items.map((design) => (
          <DesignApprovalCard key={design.id} design={design} highlighted={design.id === highlightId} />
        ))}
      </div>
    </div>
  );
}

export default function ApprovalPage() {
  return (
    <Suspense fallback={<LoadingSpinner label="Loading..." className="mx-auto mt-16" />}>
      <ApprovalPageContent />
    </Suspense>
  );
}

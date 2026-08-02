"use client";

import { useEffect, useState } from "react";

import { apiClient } from "@/lib/api";
import { APPROVAL_ROLES } from "@/types/design";

/**
 * One-time (non-live) fetch of each design's approval rate, for summary
 * table display. Unlike useApprovalStatus, this doesn't poll or open a
 * WebSocket per row — it's a batch snapshot for a list of designs.
 */
export function useApprovalRates(designIds: string[]): Map<string, number | null> {
  const [rates, setRates] = useState<Map<string, number | null>>(new Map());

  useEffect(() => {
    let cancelled = false;

    async function loadAll() {
      const entries = await Promise.all(
        designIds.map(async (id): Promise<[string, number | null]> => {
          try {
            const approval = await apiClient.getApproval(id);
            if (!approval) return [id, null];
            const approvedCount = APPROVAL_ROLES.filter(
              (role) => approval.approvals[role]?.decision === "approved"
            ).length;
            return [id, (approvedCount / APPROVAL_ROLES.length) * 100];
          } catch {
            return [id, null];
          }
        })
      );
      if (!cancelled) setRates(new Map(entries));
    }

    if (designIds.length > 0) loadAll();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [designIds.join(",")]);

  return rates;
}

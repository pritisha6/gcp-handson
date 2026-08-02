"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { apiClient, ApiError } from "@/lib/api";
import { WS_BASE_URL } from "@/lib/constants";
import type { Approval } from "@/types/design";

const POLL_INTERVAL_MS = 15000;
const RECONNECT_BASE_DELAY_MS = 2000;
const MAX_RECONNECT_ATTEMPTS = 3;

export interface UseApprovalStatusResult {
  approval: Approval | null;
  loading: boolean;
  error: string | null;
  /** True once a live WebSocket connection is active; false while falling back to polling. */
  isLive: boolean;
  refresh: () => Promise<void>;
}

/**
 * Tracks a design's approval status in near-real-time.
 *
 * Attempts a WebSocket connection first; if it can't connect (the backend
 * doesn't expose an approval-workflow WebSocket yet) or the connection
 * drops, falls back to polling on an interval after a few reconnect
 * attempts. Callers don't need to know which transport is active, only
 * `isLive` for an optional "live" indicator in the UI.
 */
export function useApprovalStatus(designId: string | null): UseApprovalStatusResult {
  const [approval, setApproval] = useState<Approval | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isLive, setIsLive] = useState(false);

  const socketRef = useRef<WebSocket | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const reconnectAttempts = useRef(0);

  const fetchOnce = useCallback(async () => {
    if (!designId) return;
    try {
      const result = await apiClient.getApproval(designId);
      setApproval(result);
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load approval status.");
    } finally {
      setLoading(false);
    }
  }, [designId]);

  useEffect(() => {
    if (!designId) return;
    let cancelled = false;

    const stopPolling = () => {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
    const startPolling = () => {
      if (pollRef.current) return;
      pollRef.current = setInterval(fetchOnce, POLL_INTERVAL_MS);
    };

    setLoading(true);
    fetchOnce();

    function connect() {
      if (cancelled) return;
      try {
        const socket = new WebSocket(`${WS_BASE_URL}/api/designs/${encodeURIComponent(designId as string)}/approval/ws`);
        socketRef.current = socket;

        socket.onopen = () => {
          if (cancelled) return;
          setIsLive(true);
          reconnectAttempts.current = 0;
          stopPolling();
        };

        socket.onmessage = (event) => {
          try {
            setApproval(JSON.parse(event.data) as Approval);
            setError(null);
          } catch {
            // ignore malformed frames
          }
        };

        socket.onerror = () => socket.close();

        socket.onclose = () => {
          if (cancelled) return;
          setIsLive(false);
          if (reconnectAttempts.current < MAX_RECONNECT_ATTEMPTS) {
            reconnectAttempts.current += 1;
            setTimeout(connect, RECONNECT_BASE_DELAY_MS * reconnectAttempts.current);
          } else {
            startPolling();
          }
        };
      } catch {
        startPolling();
      }
    }

    connect();

    return () => {
      cancelled = true;
      socketRef.current?.close();
      stopPolling();
    };
  }, [designId, fetchOnce]);

  return { approval, loading, error, isLive, refresh: fetchOnce };
}

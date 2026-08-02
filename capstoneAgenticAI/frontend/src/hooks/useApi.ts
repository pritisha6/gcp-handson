"use client";

import { useCallback, useRef, useState } from "react";

import { ApiError } from "@/lib/api";

export interface UseApiOptions {
  /** Number of retry attempts for network/5xx failures. Default 2. */
  retries?: number;
  /** Base delay in ms between retries; grows linearly with attempt number. Default 500. */
  retryDelayMs?: number;
}

export interface UseApiState<TResult> {
  data: TResult | null;
  loading: boolean;
  error: string | null;
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function isRetryable(error: unknown): boolean {
  if (!(error instanceof ApiError)) return false;
  return error.status === 0 || error.status >= 500;
}

/**
 * Wraps an async API call with loading/error/data state and automatic
 * retry for transient (network or 5xx) failures. Client-side errors
 * (4xx) fail immediately without retrying.
 */
export function useApi<TArgs extends unknown[], TResult>(
  apiFn: (...args: TArgs) => Promise<TResult>,
  options: UseApiOptions = {}
) {
  const { retries = 2, retryDelayMs = 500 } = options;
  const [state, setState] = useState<UseApiState<TResult>>({
    data: null,
    loading: false,
    error: null,
  });
  const apiFnRef = useRef(apiFn);
  apiFnRef.current = apiFn;

  const execute = useCallback(
    async (...args: TArgs): Promise<TResult> => {
      setState({ data: null, loading: true, error: null });

      let attempt = 0;
      // eslint-disable-next-line no-constant-condition
      while (true) {
        try {
          const result = await apiFnRef.current(...args);
          setState({ data: result, loading: false, error: null });
          return result;
        } catch (err) {
          const canRetry = attempt < retries && isRetryable(err);
          if (!canRetry) {
            const message =
              err instanceof ApiError ? err.message : "An unexpected error occurred.";
            setState({ data: null, loading: false, error: message });
            throw err;
          }
          attempt += 1;
          await delay(retryDelayMs * attempt);
        }
      }
    },
    [retries, retryDelayMs]
  );

  const reset = useCallback(() => {
    setState({ data: null, loading: false, error: null });
  }, []);

  return { ...state, execute, reset };
}

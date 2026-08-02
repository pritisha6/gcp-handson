import { API_BASE_URL } from "@/lib/constants";
import type {
  Alert,
  Approval,
  CreateDesignRequest,
  CreateDesignResponse,
  DeleteDesignResponse,
  Design,
  DesignMetrics,
  ErrorResponse,
  GuardrailResult,
  ListDesignsParams,
  ListDesignsResponse,
  MetricsSnapshot,
  Requirement,
  SubmitApprovalRequest,
  TrendsResponse,
  UpdateDesignRequest,
} from "@/types/design";

/** Error thrown by ApiClient with a message safe to show directly to users. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: Record<string, unknown>;
  readonly correlationId?: string | null;

  constructor(
    message: string,
    status: number,
    code = "unknown_error",
    details: Record<string, unknown> = {},
    correlationId?: string | null
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
    this.correlationId = correlationId;
  }
}

function friendlyMessageFor(status: number, fallback: string): string {
  switch (status) {
    case 400:
      return fallback || "The request was invalid. Please check your input and try again.";
    case 404:
      return fallback || "The requested design could not be found.";
    case 409:
      return fallback || "This design already exists.";
    case 422:
      return fallback || "Some fields failed validation. Please review the form.";
    case 502:
    case 503:
      return "The server is temporarily unavailable. Please try again shortly.";
    default:
      if (status >= 500) {
        return "Something went wrong on our end. Please try again.";
      }
      return fallback || "An unexpected error occurred.";
  }
}

/** Typed HTTP client for the ETL Design Agent backend API. */
export class ApiClient {
  constructor(private readonly baseUrl: string = API_BASE_URL) {}

  private async request<T>(path: string, init?: RequestInit): Promise<T> {
    let response: Response;
    try {
      response = await fetch(`${this.baseUrl}${path}`, {
        ...init,
        headers: {
          "Content-Type": "application/json",
          ...init?.headers,
        },
      });
    } catch {
      throw new ApiError(
        "Could not reach the server. Check your connection and that the API is running.",
        0,
        "network_error"
      );
    }

    if (response.status === 204) {
      return undefined as T;
    }

    const contentType = response.headers.get("content-type") ?? "";
    const body = contentType.includes("application/json") ? await response.json() : undefined;

    if (!response.ok) {
      const errorBody = body as ErrorResponse | undefined;
      const message = friendlyMessageFor(response.status, errorBody?.error?.message ?? "");
      throw new ApiError(
        message,
        response.status,
        errorBody?.error?.code ?? "http_error",
        errorBody?.error?.details ?? {},
        errorBody?.correlation_id
      );
    }

    return body as T;
  }

  /**
   * Create a new design. Returns the minimal, immediately-available
   * record; the full design (with generated output) becomes available
   * asynchronously via getDesign().
   */
  async createDesign(request: CreateDesignRequest): Promise<CreateDesignResponse> {
    return this.request<CreateDesignResponse>("/api/designs/create", {
      method: "POST",
      body: JSON.stringify(request),
    });
  }

  async getDesign(designId: string): Promise<Design> {
    return this.request<Design>(`/api/designs/${encodeURIComponent(designId)}`, {
      method: "GET",
    });
  }

  async listDesigns(params: ListDesignsParams = {}): Promise<ListDesignsResponse> {
    const query = new URLSearchParams();
    if (params.skip !== undefined) query.set("skip", String(params.skip));
    if (params.limit !== undefined) query.set("limit", String(params.limit));
    if (params.status) query.set("status", params.status);
    if (params.dateFrom) query.set("date_from", params.dateFrom);
    if (params.dateTo) query.set("date_to", params.dateTo);

    const qs = query.toString();
    return this.request<ListDesignsResponse>(`/api/designs${qs ? `?${qs}` : ""}`, {
      method: "GET",
    });
  }

  async updateDesign(designId: string, updates: UpdateDesignRequest): Promise<Design> {
    return this.request<Design>(`/api/designs/${encodeURIComponent(designId)}`, {
      method: "PATCH",
      body: JSON.stringify(updates),
    });
  }

  async deleteDesign(designId: string): Promise<DeleteDesignResponse> {
    return this.request<DeleteDesignResponse>(`/api/designs/${encodeURIComponent(designId)}`, {
      method: "DELETE",
    });
  }

  async validateRequirements(requirements: Requirement): Promise<GuardrailResult[]> {
    return this.request<GuardrailResult[]>("/api/validate/requirements", {
      method: "POST",
      body: JSON.stringify(requirements),
    });
  }

  async validateDesign(design: Design): Promise<GuardrailResult[]> {
    return this.request<GuardrailResult[]>("/api/validate/design", {
      method: "POST",
      body: JSON.stringify(design),
    });
  }

  /**
   * Fetch the approval state for a design. The approval-workflow API is not
   * yet implemented on the backend (tracked as future work); a 404 here is
   * treated as "no approvals recorded yet" rather than an error, so the UI
   * can render an empty-but-valid checklist instead of breaking.
   */
  async getApproval(designId: string): Promise<Approval | null> {
    try {
      return await this.request<Approval>(`/api/designs/${encodeURIComponent(designId)}/approval`, {
        method: "GET",
      });
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        return null;
      }
      throw err;
    }
  }

  async submitApproval(designId: string, request: SubmitApprovalRequest): Promise<Approval> {
    return this.request<Approval>(`/api/designs/${encodeURIComponent(designId)}/approval`, {
      method: "POST",
      body: JSON.stringify(request),
    });
  }

  /**
   * Fetch aggregate quality/reliability/efficiency/impact metrics. A 404
   * (e.g. the endpoint unreachable in this environment) is treated as "no
   * data" rather than an error, so MetricsDashboard shows an empty state
   * instead of crashing.
   */
  async getMetrics(): Promise<MetricsSnapshot | null> {
    try {
      return await this.request<MetricsSnapshot>("/api/metrics", { method: "GET" });
    } catch (err) {
      if (err instanceof ApiError && (err.status === 404 || err.status === 0)) {
        return null;
      }
      throw err;
    }
  }

  async getDesignMetrics(limit = 100): Promise<DesignMetrics[]> {
    return this.request<DesignMetrics[]>(`/api/metrics/designs?limit=${limit}`, { method: "GET" });
  }

  async getTrends(days = 30): Promise<TrendsResponse> {
    return this.request<TrendsResponse>(`/api/metrics/trends?days=${days}`, { method: "GET" });
  }

  /**
   * Fetch currently active threshold-crossing alerts. Safe to poll for a UI
   * widget: the backend only dispatches Slack/email notifications when
   * explicitly asked to (``notify=true``), which this client never passes.
   */
  async getAlerts(): Promise<Alert[]> {
    return this.request<Alert[]>("/api/metrics/alerts", { method: "GET" });
  }

  /**
   * Upload a single file with progress reporting. Uses XMLHttpRequest
   * because fetch cannot report upload progress.
   */
  uploadFile(
    file: File,
    onProgress?: (percent: number) => void,
    signal?: AbortSignal
  ): Promise<{ file_id: string; filename: string }> {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", `${this.baseUrl}/api/uploads`);

      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable && onProgress) {
          onProgress(Math.round((event.loaded / event.total) * 100));
        }
      };

      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          try {
            resolve(JSON.parse(xhr.responseText));
          } catch {
            reject(new ApiError("Received an invalid response from the server.", xhr.status));
          }
        } else {
          let message = "Failed to upload file.";
          try {
            const parsed = JSON.parse(xhr.responseText) as ErrorResponse;
            message = friendlyMessageFor(xhr.status, parsed.error?.message ?? "");
          } catch {
            message = friendlyMessageFor(xhr.status, "");
          }
          reject(new ApiError(message, xhr.status));
        }
      };

      xhr.onerror = () => {
        reject(new ApiError("Could not reach the server while uploading.", 0, "network_error"));
      };

      xhr.onabort = () => {
        reject(new ApiError("Upload cancelled.", 0, "aborted"));
      };

      if (signal) {
        signal.addEventListener("abort", () => xhr.abort());
      }

      const formData = new FormData();
      formData.append("file", file);
      xhr.send(formData);
    });
  }
}

export const apiClient = new ApiClient();

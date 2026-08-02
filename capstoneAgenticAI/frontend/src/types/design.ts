/**
 * TypeScript mirrors of the backend Pydantic models
 * (see backend/app/schemas/design.py and backend/app/schemas/api_models.py).
 */

export type DataSourceType = "DB" | "API" | "File" | "Messaging";

export type DesignStatus =
  | "pending"
  | "in_progress"
  | "completed"
  | "failed"
  | "deleted";

export type ApprovalDecisionValue = "pending" | "approved" | "rejected";

export type FinalStatus = "pending" | "approved" | "rejected";

export interface DataSource {
  name: string;
  type: DataSourceType;
  size_gb: number;
  throughput_records_sec: number;
}

export interface Performance {
  latency_sla_minutes: number;
  peak_throughput_msgs_sec: number;
  data_freshness: string;
  p95_latency_minutes: number;
}

export interface Budget {
  monthly_cap_usd: number;
  currency: string;
}

export interface Team {
  size: number;
  skills: string[];
}

export interface Compliance {
  data_types: string[];
  regulations: string[];
  data_residency: string | null;
  encryption: boolean;
}

export interface Requirement {
  data_sources: DataSource[];
  performance: Performance;
  budget: Budget;
  team: Team;
  compliance: Compliance;
  context?: string | null;
}

// --- Guardrail validation (see backend/app/schemas/guardrail.py) ---

export type GuardrailStatusValue = "PASS" | "FLAG" | "ESCALATE" | "STOP";
export type GuardrailSeverityValue = "INFO" | "WARN" | "ERROR";

export interface GuardrailResult {
  status: GuardrailStatusValue;
  severity: GuardrailSeverityValue;
  message: string;
  field?: string | null;
  remediation?: string | null;
  source: string;
}

// --- Conflicts (see backend/app/schemas/conflict.py) ---

export type ConflictSeverityValue = "INFO" | "WARNING" | "ERROR";

export interface Conflict {
  type: string;
  severity: ConflictSeverityValue;
  fields_involved: string[];
  description: string;
  suggested_resolution: string;
}

// --- DesignOutput sub-shapes as actually produced by ArchitectAgent ---
// (backend/app/services/architect_agent.py `_assemble_design`). Kept as the
// raw, loosely-typed shape the API returns; see lib/design-adapters.ts for
// normalizers that turn these into the richer shapes the UI components want.

export interface RawDecisionMatrix {
  selected_path?: string[];
  final_score?: number | null;
  alternatives?: { path: string[]; cumulative_score: number }[];
  reasoning?: string | null;
  conflicts?: Conflict[];
  validation_issues?: string[];
}

export interface RawCostAnalysis {
  total_usd?: number;
  currency?: string;
  breakdown?: Record<string, number>;
  budget_justification?: string | null;
}

export interface RawComplianceChecklist {
  [regulation: string]: {
    rule?: {
      regulation?: string;
      description?: string;
      requires_encryption?: boolean;
      requires_data_residency?: boolean;
      allowed_regions?: string[];
      applicable_data_types?: string[];
    };
    satisfied?: boolean;
  };
}

export interface RawRoadmapPhase {
  phase: number;
  name: string;
  service?: string | null;
  start_week?: number;
  duration_weeks?: number;
  depends_on?: number[];
  resources?: string[];
}

export interface RawImplementationRoadmap {
  phases?: RawRoadmapPhase[];
  disaster_recovery?: string;
}

export interface DesignOutput {
  architecture_diagram?: string | null;
  decision_matrix?: RawDecisionMatrix | null;
  cost_analysis?: RawCostAnalysis | null;
  compliance_checklist?: RawComplianceChecklist | null;
  implementation_roadmap?: RawImplementationRoadmap | null;
}

export interface Design {
  id: string;
  project_name: string;
  requirements: Requirement;
  status: DesignStatus;
  output?: DesignOutput | null;
  validation_results: GuardrailResult[];
  generation_seconds?: number | null;
  api_calls_count?: number;
  api_cost_usd?: number;
  created_at: string;
  updated_at: string;
}

export type ApprovalRole = "engineer" | "architect" | "cfo" | "security" | "ops";

export const APPROVAL_ROLES: ApprovalRole[] = ["engineer", "architect", "cfo", "security", "ops"];

export interface ApprovalEntry {
  decision: ApprovalDecisionValue;
  comment?: string | null;
  decided_at?: string | null;
}

export interface Approvals {
  engineer: ApprovalEntry;
  architect: ApprovalEntry;
  cfo: ApprovalEntry;
  security: ApprovalEntry;
  ops: ApprovalEntry;
}

export interface Approval {
  design_id: string;
  approvals: Approvals;
  final_status: FinalStatus;
  final_decision?: string | null;
}

/**
 * Request body for submitting a stakeholder's approval decision.
 *
 * NOTE: the backend does not yet expose an approval-workflow API (it's
 * referenced as future work — "approval_workflow.py" — in the guardrail
 * system's integration notes). This is the contract the frontend expects;
 * calls against it degrade gracefully (see lib/api.ts) until it exists.
 */
export interface SubmitApprovalRequest {
  role: ApprovalRole;
  decision: ApprovalDecisionValue;
  comment?: string;
}

// --- API request/response models (see backend/app/schemas/api_models.py) ---

export interface CreateDesignRequest {
  project_name: string;
  requirements: Requirement;
}

export interface CreateDesignResponse {
  id: string;
  project_name: string;
  status: DesignStatus;
  created_at: string;
}

export interface UpdateDesignRequest {
  project_name?: string;
  requirements?: Requirement;
  status?: DesignStatus;
  output?: DesignOutput;
}

export interface PaginationMeta {
  skip: number;
  limit: number;
  total: number;
}

export interface ListDesignsResponse {
  items: Design[];
  pagination: PaginationMeta;
}

export interface DeleteDesignResponse {
  id: string;
  status: DesignStatus;
  deleted: boolean;
}

export interface ErrorDetail {
  code: string;
  message: string;
  details: Record<string, unknown>;
}

export interface ErrorResponse {
  error: ErrorDetail;
  correlation_id?: string | null;
}

export interface ListDesignsParams {
  skip?: number;
  limit?: number;
  status?: DesignStatus;
  dateFrom?: string;
  dateTo?: string;
}

// --- Metrics dashboard (see backend/app/schemas/metrics.py) ---

export interface QualityMetrics {
  requirement_coverage_pct: number;
  /** Guardrail pass rate, used as a general accuracy proxy. */
  accuracy_pct: number;
  /** Proxy for architecture headroom vs. peak load (from GR 3.4). */
  scalability_score: number;
}

export interface ReliabilityMetrics {
  approval_rate_pct: number;
  /** Proxy: how decisively the Tree-of-Thought search converged on one path. */
  consistency_pct: number;
  hallucination_rate_pct: number;
}

export interface EfficiencyMetrics {
  avg_generation_time_minutes: number;
  avg_api_calls: number;
  avg_api_cost_usd: number;
}

export interface UserImpactMetrics {
  /** Proxy: approval rate scaled to a 0-5 score (no explicit satisfaction survey exists yet). */
  satisfaction_score: number;
  avg_time_saved_hours: number;
  /** Sum of ROI business-benefit figures found in cost-guardrail remediation text. */
  business_value_usd: number;
}

export interface TrendPoint {
  date: string;
  value: number;
}

export interface ApprovalRateByStakeholder {
  role: ApprovalRole;
  approval_rate_pct: number;
}

export interface MetricsSnapshot {
  quality: QualityMetrics;
  reliability: ReliabilityMetrics;
  efficiency: EfficiencyMetrics;
  user_impact: UserImpactMetrics;
  coverage_trend: TrendPoint[];
  approval_rate_by_stakeholder: ApprovalRateByStakeholder[];
  cost_accuracy_distribution: number[];
  /** Raw per-design generation times in minutes, for a percentile/box-plot chart. */
  generation_time_minutes_samples: number[];
  sample_size: number;
}

export interface TrendsResponse {
  coverage_trend: TrendPoint[];
  cost_trend: TrendPoint[];
  generation_time_trend: TrendPoint[];
}

export interface DesignMetrics {
  design_id: string;
  project_name: string;
  status: string;
  requirement_coverage_pct: number | null;
  compliance_pass_rate_pct: number | null;
  approval_rate_pct: number | null;
  total_cost_usd: number | null;
  generation_seconds: number | null;
  api_calls_count: number;
  api_cost_usd: number;
  hallucination_count: number;
  created_at: string;
}

// --- Alerts (see backend/app/services/alert_service.py) ---

export type AlertSeverityValue = "WARNING" | "CRITICAL";

export interface Alert {
  metric: string;
  severity: AlertSeverityValue;
  threshold: number;
  current_value: number;
  message: string;
  triggered_at: string;
}

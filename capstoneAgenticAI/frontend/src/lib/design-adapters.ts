/**
 * Adapters that normalize the (currently fairly sparse) raw shapes the
 * backend sends in `DesignOutput` into richer view-models the UI components
 * are built against.
 *
 * Several fields the design spec calls for (per-candidate latency/cost/ops
 * score breakdowns, roadmap week numbers, ROI baselines) aren't persisted by
 * the backend today — see each function's docstring for exactly what's
 * derived vs. what's an honest placeholder. Every function also accepts the
 * richer shape directly (fields like `start_week` on a roadmap phase), so
 * nothing needs to change here if the backend starts sending more.
 */
import {
  ARCHITECTURE_LAYERS,
  DEFAULT_PHASE_TIMELINE,
} from "@/lib/constants";
import type {
  GuardrailResult,
  RawComplianceChecklist,
  RawCostAnalysis,
  RawDecisionMatrix,
  RawImplementationRoadmap,
} from "@/types/design";

// --- Decision matrix ---

export interface DecisionMatrixRow {
  service: string;
  layer: string;
  latencyScore: number | null;
  costScore: number | null;
  opsScore: number | null;
  complianceScore: number | null;
  finalScore: number | null;
  status: "selected" | "alternative" | "pruned";
  reasoning?: string;
}

export interface DecisionMatrixView {
  rows: DecisionMatrixRow[];
  /** False when the backend only gave us the winning path, not per-candidate score breakdowns. */
  hasDetailedScores: boolean;
  selectedPath: string[];
  finalScore: number | null;
  reasoning: string;
  alternativePaths: { path: string[]; cumulativeScore: number }[];
}

/** The backend persists the winning path + alternative complete paths, but
 * not the per-candidate latency/cost/ops/compliance breakdown computed
 * transiently during the Tree-of-Thought search. Rows are synthesized from
 * the winning path (one row per layer, status="selected", only the overall
 * final_score available) until that richer data is persisted.
 */
export function normalizeDecisionMatrix(raw: RawDecisionMatrix | null | undefined): DecisionMatrixView {
  const selectedPath = raw?.selected_path ?? [];
  const finalScore = raw?.final_score ?? null;
  const reasoning = raw?.reasoning ?? "";
  const alternativePaths = (raw?.alternatives ?? []).map((a) => ({
    path: a.path,
    cumulativeScore: a.cumulative_score,
  }));

  const rows: DecisionMatrixRow[] = selectedPath.map((service, index) => ({
    service,
    layer: ARCHITECTURE_LAYERS[index] ?? `layer_${index + 1}`,
    latencyScore: null,
    costScore: null,
    opsScore: null,
    complianceScore: null,
    finalScore,
    status: "selected",
  }));

  return { rows, hasDetailedScores: false, selectedPath, finalScore, reasoning, alternativePaths };
}

// --- Cost analysis ---

export interface CostBreakdownItem {
  component: string;
  amount: number;
}

export interface SensitivityRow {
  scenario: string;
  costDeltaUsd: number;
  newTotalUsd: number;
}

export interface CostAnalysisView {
  totalUsd: number;
  currency: string;
  breakdown: CostBreakdownItem[];
  budgetCapUsd: number;
  overageUsd: number;
  overagePct: number;
  isOverBudget: boolean;
  budgetJustification: string | null;
  /** Approximate, client-side "what if" estimates — not a live backend recompute. */
  sensitivity: SensitivityRow[];
}

const THROUGHPUT_SENSITIVE_COMPONENTS = ["ingestion", "processing"];

export function normalizeCostAnalysis(
  raw: RawCostAnalysis | null | undefined,
  budgetCapUsd: number
): CostAnalysisView {
  const totalUsd = raw?.total_usd ?? 0;
  const currency = raw?.currency ?? "USD";
  const breakdown = Object.entries(raw?.breakdown ?? {}).map(([component, amount]) => ({
    component,
    amount: Number(amount),
  }));

  const overageUsd = Math.max(0, totalUsd - budgetCapUsd);
  const overagePct = budgetCapUsd > 0 ? (overageUsd / budgetCapUsd) * 100 : 0;

  const throughputSensitiveTotal = breakdown
    .filter((b) => THROUGHPUT_SENSITIVE_COMPONENTS.includes(b.component))
    .reduce((sum, b) => sum + b.amount, 0);

  const sensitivity: SensitivityRow[] = [0.2, 0.5].map((pct) => ({
    scenario: `Throughput +${pct * 100}%`,
    costDeltaUsd: throughputSensitiveTotal * pct,
    newTotalUsd: totalUsd + throughputSensitiveTotal * pct,
  }));

  return {
    totalUsd,
    currency,
    breakdown,
    budgetCapUsd,
    overageUsd,
    overagePct,
    isOverBudget: overageUsd > 0,
    budgetJustification: raw?.budget_justification ?? null,
    sensitivity,
  };
}

// --- Compliance checklist ---

export interface ComplianceControlRow {
  regulation: string;
  control: string;
  status: "included" | "partial" | "missing";
  service: string | null;
  costEstimate: string | null;
  notes: string | null;
}

function extractCostFromRemediation(remediation: string | null | undefined): string | null {
  if (!remediation) return null;
  const match = remediation.match(/~?\$[\d,]+(\.\d+)?\/mo/);
  return match ? match[0] : null;
}

/** Derives one row per known control flag on each regulation's rule
 * (encryption, data residency); rules without specific flags produce one
 * general-status row. Cost estimates come from the matching guardrail
 * result's remediation text (GR 2.3/3.3), when a gap was found there.
 */
export function normalizeComplianceChecklist(
  raw: RawComplianceChecklist | null | undefined,
  validationResults: GuardrailResult[]
): ComplianceControlRow[] {
  if (!raw) return [];
  const rows: ComplianceControlRow[] = [];

  for (const [regulation, entry] of Object.entries(raw)) {
    const rule = entry.rule ?? {};
    const satisfied = entry.satisfied ?? false;
    const gapResult = validationResults.find(
      (r) => r.source.includes("Compliance Gap") && r.source.includes(regulation)
    );
    const costEstimate = extractCostFromRemediation(gapResult?.remediation);

    if (rule.requires_encryption) {
      rows.push({
        regulation,
        control: "Encryption at rest/in transit (CMEK)",
        status: satisfied ? "included" : "missing",
        service: satisfied ? "Cloud KMS" : null,
        costEstimate: satisfied ? null : costEstimate,
        notes: satisfied ? "Fully compliant" : gapResult?.message ?? "Control not yet in place",
      });
    }
    if (rule.requires_data_residency) {
      const regionLabel = rule.allowed_regions?.length ? ` (${rule.allowed_regions.join(", ")})` : "";
      rows.push({
        regulation,
        control: `Data residency${regionLabel}`,
        status: satisfied ? "included" : "missing",
        service: satisfied ? "Regional storage/BigQuery config" : null,
        costEstimate: satisfied ? null : costEstimate,
        notes: satisfied ? "Fully compliant" : gapResult?.message ?? "Control not yet in place",
      });
    }
    if (!rule.requires_encryption && !rule.requires_data_residency) {
      rows.push({
        regulation,
        control: "General controls",
        status: satisfied ? "included" : "partial",
        service: null,
        costEstimate: null,
        notes: rule.description ?? null,
      });
    }
  }
  return rows;
}

// --- Implementation roadmap ---

export interface RoadmapPhaseView {
  phase: number;
  name: string;
  service: string | null;
  startWeek: number;
  durationWeeks: number;
  endWeek: number;
  dependsOn: number[];
  isEstimated: boolean;
}

/** Uses explicit start_week/duration_weeks/depends_on when the backend
 * provides them; otherwise falls back to a sensible default timeline
 * (Infrastructure -> Connectors -> Testing -> Cutover) and marks the phase
 * `isEstimated` so the UI can label it as such rather than presenting a
 * guess as fact.
 */
// --- History table derived metrics ---
// Neither "requirement coverage %" nor "compliance %" is a first-class
// Design field; both are derived from the GR 3.1/3.3 guardrail results
// recorded in Design.validation_results, so the history table shows real
// (if approximate) numbers rather than fabricating them.

export function extractCoveragePct(validationResults: GuardrailResult[]): number | null {
  const result = validationResults.find((r) => r.source.startsWith("GR 3.1"));
  if (!result) return null;
  const match = result.message.match(/(\d+(\.\d+)?)%/);
  return match ? Number(match[1]) : null;
}

export function extractCompliancePct(validationResults: GuardrailResult[]): number | null {
  const complianceResults = validationResults.filter((r) => r.source.includes("Compliance"));
  if (complianceResults.length === 0) return null;
  const passCount = complianceResults.filter((r) => r.status === "PASS").length;
  return (passCount / complianceResults.length) * 100;
}

export function normalizeRoadmap(raw: RawImplementationRoadmap | null | undefined): RoadmapPhaseView[] {
  const phases = raw?.phases ?? [];
  return phases.map((phase, index) => {
    const fallback = DEFAULT_PHASE_TIMELINE[index] ?? { start_week: index + 1, duration_weeks: 1 };
    const startWeek = phase.start_week ?? fallback.start_week;
    const durationWeeks = phase.duration_weeks ?? fallback.duration_weeks;
    const previousPhaseNumber = index > 0 ? phases[index - 1]?.phase : undefined;

    return {
      phase: phase.phase,
      name: phase.name,
      service: phase.service ?? null,
      startWeek,
      durationWeeks,
      endWeek: startWeek + durationWeeks - 1,
      dependsOn: phase.depends_on ?? (previousPhaseNumber !== undefined ? [previousPhaseNumber] : []),
      isEstimated: phase.start_week === undefined || phase.duration_weeks === undefined,
    };
  });
}

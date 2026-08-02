"""Schemas for observability metrics, trends, and alerts.

Every field here is computed from data this system actually persists
(``Design.validation_results``, ``Approval`` documents, generation
timing/API-usage counters). Where a genuinely accurate signal doesn't
exist yet (e.g. true post-deployment cost accuracy, which would need a
feedback loop this system doesn't have), the computing method uses a
clearly-documented proxy rather than a fabricated number — see
``app.services.metrics_service`` for exactly how each field is derived.
"""
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class QualityMetrics(BaseModel):
    """Design Quality: coverage, accuracy, scalability."""

    requirement_coverage_pct: float = Field(..., ge=0, le=100, description="Average GR 3.1 requirement coverage")
    accuracy_pct: float = Field(..., ge=0, le=100, description="Guardrail pass rate, used as an accuracy proxy")
    scalability_score: float = Field(
        ..., ge=0, le=100, description="Proxy for architecture headroom vs. peak load, from GR 3.4"
    )


class ReliabilityMetrics(BaseModel):
    """Reliability: approval rate, consistency, hallucinations."""

    approval_rate_pct: float = Field(..., ge=0, le=100)
    consistency_pct: float = Field(
        ..., ge=0, le=100, description="Proxy: how decisively the search converged on one path"
    )
    hallucination_rate_pct: float = Field(
        ..., ge=0, le=100, description="Share of designs with at least one flagged claim"
    )


class EfficiencyMetrics(BaseModel):
    """Efficiency: generation time, API calls, cost."""

    avg_generation_time_minutes: float = Field(..., ge=0)
    avg_api_calls: float = Field(..., ge=0)
    avg_api_cost_usd: float = Field(..., ge=0)


class UserImpactMetrics(BaseModel):
    """User impact: satisfaction, time saved, business value."""

    satisfaction_score: float = Field(..., ge=0, le=5, description="Proxy: approval rate scaled to a 0-5 score")
    avg_time_saved_hours: float = Field(
        ..., description="Assumed manual design time (see ASSUMED_MANUAL_DESIGN_HOURS) minus actual generation time"
    )
    business_value_usd: float = Field(
        ..., ge=0, description="Sum of ROI business-benefit figures found in cost-guardrail remediation text"
    )


class TrendPoint(BaseModel):
    """One point on a time-series chart."""

    date: str = Field(..., description="ISO date, e.g. '2026-07-01'")
    value: float


class ApprovalRateByStakeholder(BaseModel):
    """Approval rate for one stakeholder role, across all designs."""

    role: str
    approval_rate_pct: float = Field(..., ge=0, le=100)


class MetricsSnapshot(BaseModel):
    """Aggregate metrics across all (non-deleted) designs."""

    quality: QualityMetrics
    reliability: ReliabilityMetrics
    efficiency: EfficiencyMetrics
    user_impact: UserImpactMetrics
    coverage_trend: List[TrendPoint] = Field(default_factory=list, description="Last 30 days")
    approval_rate_by_stakeholder: List[ApprovalRateByStakeholder] = Field(default_factory=list)
    cost_accuracy_distribution: List[float] = Field(
        default_factory=list, description="Per-design accuracy-proxy values, for a histogram"
    )
    generation_time_minutes_samples: List[float] = Field(
        default_factory=list, description="Raw per-design generation times, for a percentile/box-plot chart"
    )
    sample_size: int = Field(..., ge=0, description="Number of designs this snapshot was computed from")


class DesignMetrics(BaseModel):
    """Per-design metrics, as stored in the ``design_metrics`` Firestore collection."""

    design_id: str
    project_name: str
    status: str
    requirement_coverage_pct: Optional[float] = None
    compliance_pass_rate_pct: Optional[float] = None
    approval_rate_pct: Optional[float] = None
    total_cost_usd: Optional[float] = None
    generation_seconds: Optional[float] = None
    api_calls_count: int = 0
    api_cost_usd: float = 0.0
    hallucination_count: int = 0
    created_at: str


class AlertSeverity(str, Enum):
    """How urgent a threshold-crossing alert is."""

    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class TrendsResponse(BaseModel):
    """Response for GET /api/metrics/trends."""

    coverage_trend: List[TrendPoint] = Field(default_factory=list)
    cost_trend: List[TrendPoint] = Field(default_factory=list)
    generation_time_trend: List[TrendPoint] = Field(default_factory=list)


class Alert(BaseModel):
    """A threshold-crossing condition detected in the current metrics snapshot."""

    metric: str = Field(..., description="Which metric crossed its threshold, e.g. 'approval_rate_pct'")
    severity: AlertSeverity
    threshold: float
    current_value: float
    message: str
    triggered_at: str

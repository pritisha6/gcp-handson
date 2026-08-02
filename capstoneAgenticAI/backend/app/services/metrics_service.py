"""Computes and stores observability metrics for designs.

Every number here is derived from data this system actually persists
(``Design.validation_results``, timing/API-usage fields recorded during
generation, and ``approvals`` Firestore documents). Where a genuinely
accurate signal doesn't exist yet -- e.g. true post-deployment cost
accuracy, or a real user-satisfaction survey -- a clearly-documented proxy
is used instead of a fabricated value; see each ``_...`` helper's
docstring for exactly how it's derived.
"""
import re
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, TypeVar

from google.api_core import exceptions as gcp_exceptions
from google.cloud import firestore

from app.config import Settings, get_settings
from app.db.firestore_client import FirestoreClient, get_firestore_client
from app.db.models import Collection
from app.schemas.design import Design
from app.schemas.metrics import (
    ApprovalRateByStakeholder,
    DesignMetrics,
    EfficiencyMetrics,
    MetricsSnapshot,
    QualityMetrics,
    ReliabilityMetrics,
    TrendPoint,
    TrendsResponse,
    UserImpactMetrics,
)
from app.utils.errors import FirestoreOperationError
from app.utils.logger import get_logger

logger = get_logger(__name__)

T = TypeVar("T")

# This system's own value proposition is generating a design in ~15-20
# minutes vs. a manual architecture review cycle; there's no feedback loop
# that tells us how long a human actually would have taken, so a documented
# assumption stands in for a measurement.
ASSUMED_MANUAL_DESIGN_HOURS = 20.0

_APPROVAL_ROLES = ("engineer", "architect", "cfo", "security", "ops")
_DECIDED_STATES = ("approved", "rejected")

# No pagination loop yet at this scale; see get_overall_metrics docstring.
_MAX_DESIGNS_FOR_AGGREGATE = 1000

_ROI_BENEFIT_RE = re.compile(r"saves ~\$([\d,]+)/mo")
_PCT_RE = re.compile(r"(\d+(?:\.\d+)?)%")

_SCALABILITY_SCORE_BY_STATUS = {"PASS": 100.0, "FLAG": 60.0, "ESCALATE": 20.0, "STOP": 0.0}


def _avg(values: List[float], default: float = 0.0) -> float:
    return sum(values) / len(values) if values else default


class MetricsService:
    """Computes per-design and aggregate metrics, and persists per-design metrics to Firestore."""

    def __init__(
        self,
        firestore_client: Optional[FirestoreClient] = None,
        raw_firestore_client: Optional[firestore.Client] = None,
        settings: Optional[Settings] = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._designs = firestore_client or get_firestore_client()
        self._raw_client = raw_firestore_client or firestore.Client(
            project=self._settings.GCP_PROJECT_ID, database=self._settings.FIRESTORE_DATABASE
        )
        self._metrics_collection = self._raw_client.collection(Collection.DESIGN_METRICS.value)
        self._approvals_collection = self._raw_client.collection(Collection.APPROVALS.value)

    # === Per-design ===

    def compute_design_metrics(self, design: Design) -> DesignMetrics:
        """Compute metrics for a single design from its own persisted data.

        Args:
            design: A design, typically one that just finished generating.

        Returns:
            The computed per-design metrics (not yet persisted; see ``store_design_metrics``).
        """
        approval_doc = self._fetch_approval_doc(design.id)
        total_cost = (design.output.cost_analysis or {}).get("total_usd") if design.output else None

        return DesignMetrics(
            design_id=design.id,
            project_name=design.project_name,
            status=design.status.value,
            requirement_coverage_pct=self._extract_coverage_pct(design),
            compliance_pass_rate_pct=self._compliance_pass_rate_pct(design),
            approval_rate_pct=self._approval_rate_from_doc(approval_doc),
            total_cost_usd=total_cost,
            generation_seconds=design.generation_seconds,
            api_calls_count=design.api_calls_count,
            api_cost_usd=design.api_cost_usd,
            hallucination_count=self._hallucination_count(design),
            created_at=design.created_at.isoformat(),
        )

    def store_design_metrics(self, metrics: DesignMetrics) -> None:
        """Persist per-design metrics to the ``design_metrics`` Firestore collection.

        Raises:
            FirestoreOperationError: On an unexpected Firestore failure.
        """
        try:
            payload = metrics.model_dump(mode="json")
            payload["updated_at"] = datetime.now(timezone.utc)
            self._metrics_collection.document(metrics.design_id).set(payload)
        except gcp_exceptions.GoogleAPICallError as exc:
            logger.exception("Failed to store metrics for design '%s'", metrics.design_id)
            raise FirestoreOperationError(f"Failed to store metrics for design '{metrics.design_id}'.") from exc

    def compute_and_store_design_metrics(self, design: Design) -> DesignMetrics:
        """Compute and persist metrics for one design in a single call."""
        metrics = self.compute_design_metrics(design)
        self.store_design_metrics(metrics)
        return metrics

    def list_design_metrics(self, limit: int = 100) -> List[DesignMetrics]:
        """Return stored per-design metrics, most recently created first.

        Raises:
            FirestoreOperationError: On an unexpected Firestore failure.
        """
        try:
            docs = self._metrics_collection.order_by("created_at", direction=firestore.Query.DESCENDING).limit(limit)
            return [DesignMetrics.model_validate(doc.to_dict()) for doc in docs.stream()]
        except gcp_exceptions.GoogleAPICallError as exc:
            logger.exception("Failed to list design metrics")
            raise FirestoreOperationError("Failed to list design metrics.") from exc

    # === Aggregate ===

    async def get_overall_metrics(self) -> MetricsSnapshot:
        """Compute an aggregate snapshot across all non-deleted designs.

        Fetches up to ``_MAX_DESIGNS_FOR_AGGREGATE`` designs directly
        (there's no paged scan yet, so a deployment with more designs than
        that will see the snapshot silently cap at the most recent batch
        returned by Firestore -- acceptable for this system's expected
        scale, but worth revisiting before that changes).

        Returns:
            A ``MetricsSnapshot`` covering quality, reliability, efficiency,
            and user-impact metrics, plus a 30-day coverage trend and
            per-stakeholder approval rates.
        """
        start = time.monotonic()
        designs = await self._designs.list_designs(skip=0, limit=_MAX_DESIGNS_FOR_AGGREGATE, filters={})
        approvals_by_design = self._fetch_all_approvals()

        coverage_values = self._collect(designs, self._extract_coverage_pct)
        guardrail_pass_values = self._collect(designs, self._guardrail_pass_rate_pct)
        scalability_values = self._collect(designs, self._scalability_score)
        consistency_values = self._collect(designs, self._consistency_pct)
        hallucination_flags = [self._hallucination_count(d) > 0 for d in designs]
        approval_rates = self._collect(
            designs, lambda d: self._approval_rate_from_doc(approvals_by_design.get(d.id))
        )
        generation_minutes = [d.generation_seconds / 60 for d in designs if d.generation_seconds is not None]
        api_calls = [float(d.api_calls_count) for d in designs if d.api_calls_count]
        api_costs = [d.api_cost_usd for d in designs if d.api_cost_usd]
        business_values = self._collect(designs, self._extract_business_value)

        snapshot = MetricsSnapshot(
            quality=QualityMetrics(
                requirement_coverage_pct=_avg(coverage_values),
                accuracy_pct=_avg(guardrail_pass_values),
                scalability_score=_avg(scalability_values),
            ),
            reliability=ReliabilityMetrics(
                approval_rate_pct=_avg(approval_rates),
                consistency_pct=_avg(consistency_values),
                hallucination_rate_pct=(sum(hallucination_flags) / len(hallucination_flags) * 100)
                if hallucination_flags
                else 0.0,
            ),
            efficiency=EfficiencyMetrics(
                avg_generation_time_minutes=_avg(generation_minutes),
                avg_api_calls=_avg(api_calls),
                avg_api_cost_usd=_avg(api_costs),
            ),
            user_impact=UserImpactMetrics(
                satisfaction_score=(_avg(approval_rates) / 100) * 5,
                avg_time_saved_hours=max(0.0, ASSUMED_MANUAL_DESIGN_HOURS - (_avg(generation_minutes) / 60)),
                business_value_usd=sum(business_values),
            ),
            coverage_trend=self._trend(designs, days=30, value_fn=self._extract_coverage_pct),
            approval_rate_by_stakeholder=self._approval_rate_by_stakeholder(approvals_by_design),
            cost_accuracy_distribution=guardrail_pass_values,
            generation_time_minutes_samples=generation_minutes,
            sample_size=len(designs),
        )

        logger.info(
            "Computed overall metrics from %d design(s) in %.1fms", len(designs), (time.monotonic() - start) * 1000
        )
        return snapshot

    async def get_trends(self, days: int = 30) -> TrendsResponse:
        """Compute coverage, cost, and generation-time trends over the last ``days`` days."""
        designs = await self._designs.list_designs(skip=0, limit=_MAX_DESIGNS_FOR_AGGREGATE, filters={})
        return TrendsResponse(
            coverage_trend=self._trend(designs, days, self._extract_coverage_pct),
            cost_trend=self._trend(
                designs, days, lambda d: (d.output.cost_analysis or {}).get("total_usd") if d.output else None
            ),
            generation_time_trend=self._trend(
                designs, days, lambda d: (d.generation_seconds / 60) if d.generation_seconds is not None else None
            ),
        )

    # --- Helpers: extraction from a single Design ---

    def _extract_coverage_pct(self, design: Design) -> Optional[float]:
        """GR 3.1's message embeds a percentage, e.g. 'coverage is 83% (5/6 dimensions)'."""
        result = next((r for r in design.validation_results if r.source.startswith("GR 3.1")), None)
        if not result:
            return None
        match = _PCT_RE.search(result.message)
        return float(match.group(1)) if match else None

    def _guardrail_pass_rate_pct(self, design: Design) -> Optional[float]:
        """Share of all guardrail checks that PASSed; used as a general accuracy/quality proxy."""
        if not design.validation_results:
            return None
        passed = sum(1 for r in design.validation_results if r.status.value == "PASS")
        return (passed / len(design.validation_results)) * 100

    def _compliance_pass_rate_pct(self, design: Design) -> Optional[float]:
        compliance_results = [r for r in design.validation_results if "Compliance" in r.source]
        if not compliance_results:
            return None
        passed = sum(1 for r in compliance_results if r.status.value == "PASS")
        return (passed / len(compliance_results)) * 100

    def _scalability_score(self, design: Design) -> Optional[float]:
        """GR 3.4 (GCP quota/limit headroom) status, mapped to a 0-100 score."""
        result = next((r for r in design.validation_results if r.source.startswith("GR 3.4")), None)
        if not result:
            return None
        return _SCALABILITY_SCORE_BY_STATUS.get(result.status.value, 50.0)

    def _consistency_pct(self, design: Design) -> Optional[float]:
        """Proxy: how decisively the Tree-of-Thought search preferred the winning path
        over its closest alternative. A larger score gap -> higher consistency. Returns
        None (excluded from averages) when there's no alternative to compare against,
        rather than assuming a search with no recorded alternatives was "fully consistent".
        """
        if not design.output or not design.output.decision_matrix:
            return None
        decision_matrix = design.output.decision_matrix
        final_score = decision_matrix.get("final_score")
        alternatives = decision_matrix.get("alternatives") or []
        if final_score is None or not alternatives:
            return None
        best_alt_score = max((alt.get("cumulative_score", 0.0) for alt in alternatives), default=0.0)
        gap = max(0.0, final_score - best_alt_score)
        return min(100.0, gap * 500)

    def _hallucination_count(self, design: Design) -> int:
        return sum(1 for r in design.validation_results if r.source.startswith("GR 4.2 Hallucinated"))

    def _extract_business_value(self, design: Design) -> Optional[float]:
        """Sum of ROI business-benefit figures CostValidator embedded in remediation text
        (only present when a current-system cost baseline was supplied for that design)."""
        for result in design.validation_results:
            if not result.remediation:
                continue
            match = _ROI_BENEFIT_RE.search(result.remediation)
            if match:
                return float(match.group(1).replace(",", ""))
        return None

    # --- Helpers: approvals ---

    def _fetch_approval_doc(self, design_id: str) -> Optional[Dict[str, Any]]:
        try:
            snapshot = self._approvals_collection.document(design_id).get()
        except gcp_exceptions.GoogleAPICallError:
            logger.exception("Failed to read approval doc for design '%s'", design_id)
            return None
        return snapshot.to_dict() if snapshot.exists else None

    def _fetch_all_approvals(self) -> Dict[str, Dict[str, Any]]:
        try:
            return {doc.id: (doc.to_dict() or {}) for doc in self._approvals_collection.stream()}
        except gcp_exceptions.GoogleAPICallError:
            logger.exception("Failed to fetch approvals for metrics aggregation")
            return {}

    def _approval_rate_from_doc(self, doc: Optional[Dict[str, Any]]) -> Optional[float]:
        if not doc:
            return None
        approvals = doc.get("approvals", {})
        approved_count = sum(1 for role in _APPROVAL_ROLES if (approvals.get(role) or {}).get("decision") == "approved")
        return (approved_count / len(_APPROVAL_ROLES)) * 100

    def _approval_rate_by_stakeholder(self, approvals_by_design: Dict[str, Dict[str, Any]]) -> List[ApprovalRateByStakeholder]:
        role_counts: Dict[str, List[int]] = {role: [0, 0] for role in _APPROVAL_ROLES}  # [approved, decided]
        for doc in approvals_by_design.values():
            approvals = doc.get("approvals", {})
            for role in _APPROVAL_ROLES:
                decision = (approvals.get(role) or {}).get("decision")
                if decision in _DECIDED_STATES:
                    role_counts[role][1] += 1
                    if decision == "approved":
                        role_counts[role][0] += 1

        return [
            ApprovalRateByStakeholder(role=role, approval_rate_pct=(approved / decided * 100) if decided else 0.0)
            for role, (approved, decided) in role_counts.items()
        ]

    # --- Helpers: generic ---

    def _collect(self, designs: List[Design], fn: Callable[[Design], Optional[T]]) -> List[T]:
        values: List[T] = []
        for design in designs:
            value = fn(design)
            if value is not None:
                values.append(value)
        return values

    def _trend(self, designs: List[Design], days: int, value_fn: Callable[[Design], Optional[float]]) -> List[TrendPoint]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        by_date: Dict[str, List[float]] = defaultdict(list)
        for design in designs:
            if design.created_at < cutoff:
                continue
            value = value_fn(design)
            if value is None:
                continue
            by_date[design.created_at.date().isoformat()].append(value)

        return [TrendPoint(date=date_str, value=_avg(values)) for date_str, values in sorted(by_date.items())]


_metrics_service: Optional[MetricsService] = None


def get_metrics_service() -> MetricsService:
    """Return a process-wide singleton MetricsService (FastAPI dependency)."""
    global _metrics_service
    if _metrics_service is None:
        _metrics_service = MetricsService()
    return _metrics_service

"""Unit tests for MetricsService's metric calculations."""
from datetime import datetime, timedelta, timezone
from typing import Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.config import Settings
from app.schemas.design import Budget, Compliance, DataSource, Design, DesignOutput, Performance, Requirement, Team
from app.schemas.guardrail import GuardrailResult, GuardrailSeverity, GuardrailStatus
from app.services.metrics_service import ASSUMED_MANUAL_DESIGN_HOURS, MetricsService


def _requirement() -> Requirement:
    return Requirement(
        data_sources=[DataSource(name="orders_db", type="DB", size_gb=10, throughput_records_sec=5)],
        performance=Performance(latency_sla_minutes=60, peak_throughput_msgs_sec=10, data_freshness="daily", p95_latency_minutes=45),
        budget=Budget(monthly_cap_usd=5000, currency="USD"),
        team=Team(size=3, skills=["python"]),
        compliance=Compliance(),
    )


def _gr(source: str, status: GuardrailStatus, message: str = "", remediation: Optional[str] = None) -> GuardrailResult:
    return GuardrailResult(
        status=status,
        severity=GuardrailSeverity.INFO,
        message=message,
        field=None,
        remediation=remediation,
        source=source,
    )


def _design(
    *,
    validation_results=None,
    generation_seconds=None,
    api_calls_count=0,
    api_cost_usd=0.0,
    decision_matrix=None,
    cost_analysis=None,
    created_at=None,
    status="completed",
) -> Design:
    output = None
    if decision_matrix is not None or cost_analysis is not None:
        output = DesignOutput(decision_matrix=decision_matrix, cost_analysis=cost_analysis)
    return Design(
        project_name="Test Design",
        requirements=_requirement(),
        status=status,
        output=output,
        validation_results=validation_results or [],
        generation_seconds=generation_seconds,
        api_calls_count=api_calls_count,
        api_cost_usd=api_cost_usd,
        created_at=created_at or datetime.now(timezone.utc),
    )


@pytest.fixture
def metrics_service() -> MetricsService:
    firestore_client = MagicMock()
    raw_client = MagicMock()
    settings = Settings(GROQ_API_KEY="k", GCP_PROJECT_ID="p", PINECONE_API_KEY="k")
    return MetricsService(firestore_client=firestore_client, raw_firestore_client=raw_client, settings=settings)


# --- Per-field extraction ---


def test_extract_coverage_pct_parses_gr_3_1_message(metrics_service: MetricsService):
    design = _design(validation_results=[_gr("GR 3.1 Requirement Coverage", GuardrailStatus.PASS, "Requirement coverage is 83% (5/6 dimensions).")])
    assert metrics_service._extract_coverage_pct(design) == 83.0


def test_extract_coverage_pct_none_when_no_gr_3_1(metrics_service: MetricsService):
    design = _design(validation_results=[_gr("GR 2.1 Latency Feasibility", GuardrailStatus.PASS)])
    assert metrics_service._extract_coverage_pct(design) is None


def test_guardrail_pass_rate_pct(metrics_service: MetricsService):
    design = _design(
        validation_results=[
            _gr("GR 1.1", GuardrailStatus.PASS),
            _gr("GR 1.2", GuardrailStatus.PASS),
            _gr("GR 1.3", GuardrailStatus.FLAG),
            _gr("GR 2.1", GuardrailStatus.STOP),
        ]
    )
    assert metrics_service._guardrail_pass_rate_pct(design) == 50.0


def test_guardrail_pass_rate_pct_none_when_no_results(metrics_service: MetricsService):
    assert metrics_service._guardrail_pass_rate_pct(_design()) is None


def test_compliance_pass_rate_pct_only_counts_compliance_sources(metrics_service: MetricsService):
    design = _design(
        validation_results=[
            _gr("GR 2.3 Compliance Check (GDPR)", GuardrailStatus.PASS),
            _gr("GR 3.3 Compliance Gap (HIPAA)", GuardrailStatus.FLAG),
            _gr("GR 2.1 Latency Feasibility", GuardrailStatus.PASS),  # not compliance-related
        ]
    )
    assert metrics_service._compliance_pass_rate_pct(design) == 50.0


@pytest.mark.parametrize(
    "status,expected",
    [(GuardrailStatus.PASS, 100.0), (GuardrailStatus.FLAG, 60.0), (GuardrailStatus.ESCALATE, 20.0), (GuardrailStatus.STOP, 0.0)],
)
def test_scalability_score_maps_gr_3_4_status(metrics_service: MetricsService, status, expected):
    design = _design(validation_results=[_gr("GR 3.4 Realistic Constraints (throughput)", status)])
    assert metrics_service._scalability_score(design) == expected


def test_consistency_pct_high_when_clear_winner(metrics_service: MetricsService):
    design = _design(decision_matrix={"final_score": 0.95, "alternatives": [{"path": ["A"], "cumulative_score": 0.70}]})
    assert metrics_service._consistency_pct(design) == 100.0  # gap of 0.25 * 500 clamps to 100


def test_consistency_pct_low_when_close_call(metrics_service: MetricsService):
    design = _design(decision_matrix={"final_score": 0.80, "alternatives": [{"path": ["A"], "cumulative_score": 0.79}]})
    assert metrics_service._consistency_pct(design) == pytest.approx(5.0)


def test_consistency_pct_none_without_alternatives(metrics_service: MetricsService):
    design = _design(decision_matrix={"final_score": 0.9, "alternatives": []})
    assert metrics_service._consistency_pct(design) is None


def test_hallucination_count(metrics_service: MetricsService):
    design = _design(
        validation_results=[
            _gr("GR 4.2 Hallucinated Claim", GuardrailStatus.FLAG),
            _gr("GR 4.2 Hallucinated Claim", GuardrailStatus.FLAG),
            _gr("GR 4.2 No Hallucinated Claims", GuardrailStatus.PASS),
        ]
    )
    assert metrics_service._hallucination_count(design) == 2


def test_extract_business_value_parses_roi_text(metrics_service: MetricsService):
    design = _design(
        validation_results=[
            _gr(
                "GR 3.2 Cost Over Budget (CAUTION)",
                GuardrailStatus.ESCALATE,
                remediation="Obtain approval. ROI: replacing the ~$12,000/mo current system saves ~$4,500/mo, an ROI of 1.5x on the $7,500/mo design cost.",
            )
        ]
    )
    assert metrics_service._extract_business_value(design) == 4500.0


def test_extract_business_value_none_when_absent(metrics_service: MetricsService):
    design = _design(validation_results=[_gr("GR 3.2 Cost Within Budget", GuardrailStatus.PASS)])
    assert metrics_service._extract_business_value(design) is None


# --- Approvals ---


def test_approval_rate_from_doc(metrics_service: MetricsService):
    doc = {
        "approvals": {
            "engineer": {"decision": "approved"},
            "architect": {"decision": "approved"},
            "cfo": {"decision": "pending"},
            "security": {"decision": "rejected"},
            "ops": {"decision": "pending"},
        }
    }
    assert metrics_service._approval_rate_from_doc(doc) == 40.0  # 2/5 approved


def test_approval_rate_from_doc_none_when_missing(metrics_service: MetricsService):
    assert metrics_service._approval_rate_from_doc(None) is None


def test_approval_rate_by_stakeholder(metrics_service: MetricsService):
    approvals_by_design = {
        "d1": {"approvals": {"engineer": {"decision": "approved"}, "architect": {"decision": "rejected"}}},
        "d2": {"approvals": {"engineer": {"decision": "approved"}}},
    }
    results = {r.role: r.approval_rate_pct for r in metrics_service._approval_rate_by_stakeholder(approvals_by_design)}
    assert results["engineer"] == 100.0  # 2/2 approved
    assert results["architect"] == 0.0  # 0/1 approved
    assert results["cfo"] == 0.0  # no decisions at all


# --- Trend bucketing ---


def test_trend_buckets_by_date_and_averages(metrics_service: MetricsService):
    now = datetime.now(timezone.utc)
    today = now.replace(hour=1)
    designs = [
        _design(created_at=today, validation_results=[_gr("GR 3.1", GuardrailStatus.PASS, "Coverage is 80% (4/5).")]),
        _design(created_at=today.replace(hour=5), validation_results=[_gr("GR 3.1", GuardrailStatus.PASS, "Coverage is 100% (5/5).")]),
    ]
    trend = metrics_service._trend(designs, days=30, value_fn=metrics_service._extract_coverage_pct)
    assert len(trend) == 1
    assert trend[0].value == 90.0


def test_trend_excludes_designs_outside_window(metrics_service: MetricsService):
    old_design = _design(
        created_at=datetime.now(timezone.utc) - timedelta(days=60),
        validation_results=[_gr("GR 3.1", GuardrailStatus.PASS, "Coverage is 100% (5/5).")],
    )
    trend = metrics_service._trend([old_design], days=30, value_fn=metrics_service._extract_coverage_pct)
    assert trend == []


# --- compute_design_metrics (end-to-end for one design) ---


def test_compute_design_metrics_end_to_end(metrics_service: MetricsService):
    design = _design(
        validation_results=[_gr("GR 3.1 Requirement Coverage", GuardrailStatus.PASS, "Requirement coverage is 90% (5/5).")],
        generation_seconds=125.0,
        api_calls_count=12,
        api_cost_usd=0.045,
        cost_analysis={"total_usd": 4200.0},
    )
    metrics_service._approvals_collection.document.return_value.get.return_value = MagicMock(exists=False)

    result = metrics_service.compute_design_metrics(design)

    assert result.design_id == design.id
    assert result.requirement_coverage_pct == 90.0
    assert result.total_cost_usd == 4200.0
    assert result.generation_seconds == 125.0
    assert result.api_calls_count == 12
    assert result.api_cost_usd == 0.045
    assert result.approval_rate_pct is None  # no approval doc mocked as existing


# --- get_overall_metrics (aggregate, async) ---


@pytest.mark.asyncio
async def test_get_overall_metrics_aggregates_across_designs(metrics_service: MetricsService):
    designs = [
        _design(
            validation_results=[_gr("GR 3.1 Requirement Coverage", GuardrailStatus.PASS, "Requirement coverage is 100% (5/5).")],
            generation_seconds=600.0,  # 10 minutes
            api_calls_count=10,
            api_cost_usd=0.05,
        ),
        _design(
            validation_results=[_gr("GR 3.1 Requirement Coverage", GuardrailStatus.PASS, "Requirement coverage is 50% (2.5/5).")],
            generation_seconds=1200.0,  # 20 minutes
            api_calls_count=20,
            api_cost_usd=0.10,
        ),
    ]
    metrics_service._designs.list_designs = AsyncMock(return_value=designs)
    metrics_service._approvals_collection.stream.return_value = []

    snapshot = await metrics_service.get_overall_metrics()

    assert snapshot.sample_size == 2
    assert snapshot.quality.requirement_coverage_pct == 75.0
    assert snapshot.efficiency.avg_generation_time_minutes == 15.0
    assert snapshot.efficiency.avg_api_calls == 15.0
    assert snapshot.user_impact.avg_time_saved_hours == pytest.approx(ASSUMED_MANUAL_DESIGN_HOURS - 15.0 / 60)

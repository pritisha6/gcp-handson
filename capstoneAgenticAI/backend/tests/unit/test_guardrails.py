"""Unit tests for the guardrail system: GuardrailValidator and its sub-validators."""
from unittest.mock import MagicMock

import pytest

from app.schemas.conflict import Conflict, ConflictSeverity
from app.schemas.design import (
    Budget,
    Compliance,
    DataSource,
    Design,
    DesignOutput,
    DesignStatus,
    Performance,
    Requirement,
    Team,
)
from app.schemas.guardrail import GuardrailResult, GuardrailSeverity, GuardrailStatus, Hallucination
from app.services.compliance_validator import ComplianceValidator
from app.services.cost_validator import CostValidator
from app.services.guardrail_validator import GuardrailValidator


def _requirement(**overrides) -> Requirement:
    base = dict(
        data_sources=[DataSource(name="orders_db", type="DB", size_gb=10, throughput_records_sec=5)],
        performance=Performance(
            latency_sla_minutes=60, peak_throughput_msgs_sec=10, data_freshness="daily", p95_latency_minutes=45
        ),
        budget=Budget(monthly_cap_usd=5000, currency="USD"),
        team=Team(size=3, skills=["python", "dataflow"]),
        compliance=Compliance(),
    )
    base.update(overrides)
    return Requirement(**base)


def _design(requirements: Requirement, **output_overrides) -> Design:
    output_fields = dict(
        architecture_diagram='flowchart LR\n    "Pub/Sub" --> "BigQuery"',
        decision_matrix={
            "selected_path": ["Pub/Sub", "Dataflow", "BigQuery", "Looker Studio"],
            "final_score": 0.9,
            "alternatives": [],
            "reasoning": "Selected Pub/Sub -> Dataflow -> BigQuery -> Looker Studio for their managed scaling.",
        },
        cost_analysis={"total_usd": 1000.0, "breakdown": {}},
        compliance_checklist={},
        implementation_roadmap={
            "phases": [
                {"phase": 1, "name": "Ingestion", "service": "Pub/Sub"},
                {"phase": 2, "name": "Processing", "service": "Dataflow"},
                {"phase": 3, "name": "Storage", "service": "BigQuery"},
                {"phase": 4, "name": "Serving", "service": "Looker Studio"},
            ]
        },
    )
    output_fields.update(output_overrides)
    return Design(
        project_name="Test Design",
        requirements=requirements,
        status=DesignStatus.COMPLETED,
        output=DesignOutput(**output_fields),
    )


@pytest.fixture
def conflict_resolver() -> MagicMock:
    mock = MagicMock()
    mock.detect_conflicts.return_value = []
    return mock


@pytest.fixture
def rag_system() -> MagicMock:
    mock = MagicMock()
    mock.get_compliance_rules.return_value = {}
    mock.retrieve_documents.return_value = []
    return mock


@pytest.fixture
def compliance_validator(rag_system: MagicMock) -> ComplianceValidator:
    return ComplianceValidator(rag_system=rag_system)


@pytest.fixture
def cost_validator() -> CostValidator:
    return CostValidator()


@pytest.fixture
def hallucination_detector() -> MagicMock:
    mock = MagicMock()
    mock.detect_hallucinations.return_value = []
    return mock


@pytest.fixture
def validator(
    conflict_resolver: MagicMock,
    compliance_validator: ComplianceValidator,
    cost_validator: CostValidator,
    hallucination_detector: MagicMock,
) -> GuardrailValidator:
    return GuardrailValidator(
        conflict_resolver=conflict_resolver,
        compliance_validator=compliance_validator,
        cost_validator=cost_validator,
        hallucination_detector=hallucination_detector,
    )


def _find(results, source_prefix: str) -> GuardrailResult:
    match = next((r for r in results if r.source.startswith(source_prefix)), None)
    assert match is not None, f"no result with source starting '{source_prefix}' in {[r.source for r in results]}"
    return match


# === SET 1: Input Validation ===


class TestValidateRequirements:
    def test_gr_1_1_passes_for_complete_requirements(self, validator: GuardrailValidator):
        results = validator.validate_requirements(_requirement())
        gr_1_1 = _find(results, "GR 1.1")
        assert gr_1_1.status == GuardrailStatus.PASS

    def test_gr_1_1_stops_for_missing_data_sources(self, validator: GuardrailValidator, conflict_resolver):
        req = _requirement()
        req.data_sources.clear()  # bypass schema's min_length for this direct unit test
        results = validator.validate_requirements(req)
        gr_1_1 = _find(results, "GR 1.1")
        assert gr_1_1.status == GuardrailStatus.STOP
        assert "data_sources" in gr_1_1.field

    def test_gr_1_2_delegates_to_conflict_resolver(self, validator: GuardrailValidator, conflict_resolver: MagicMock):
        conflict_resolver.detect_conflicts.return_value = [
            Conflict(
                type="latency_vs_freshness",
                severity=ConflictSeverity.ERROR,
                fields_involved=["performance.latency_sla_minutes"],
                description="Latency SLA conflicts with batch freshness.",
                suggested_resolution="Relax the SLA or switch to streaming.",
            )
        ]
        results = validator.validate_requirements(_requirement())
        gr_1_2 = _find(results, "GR 1.2")
        assert gr_1_2.status == GuardrailStatus.STOP
        assert gr_1_2.severity == GuardrailSeverity.ERROR
        assert gr_1_2.remediation == "Relax the SLA or switch to streaming."

    def test_gr_1_3_flags_throughput_over_partition_guidance(self, validator: GuardrailValidator):
        req = _requirement(performance=Performance(
            latency_sla_minutes=60, peak_throughput_msgs_sec=150_000, data_freshness="daily", p95_latency_minutes=45
        ))
        results = validator.validate_requirements(req)
        gr_1_3 = _find(results, "GR 1.3")
        assert gr_1_3.status == GuardrailStatus.FLAG

    def test_gr_1_3_stops_for_unrealistic_throughput(self, validator: GuardrailValidator):
        req = _requirement(performance=Performance(
            latency_sla_minutes=60, peak_throughput_msgs_sec=5_000_000, data_freshness="daily", p95_latency_minutes=45
        ))
        results = validator.validate_requirements(req)
        gr_1_3 = _find(results, "GR 1.3")
        assert gr_1_3.status == GuardrailStatus.STOP


# === SET 2: Service Selection ===


class TestValidateServiceCandidate:
    def test_scenario_latency_sla_missed_prunes_candidate(self, validator: GuardrailValidator):
        """Named scenario: latency SLA missed -> PRUNE (mapped to status=STOP)."""
        req = _requirement(performance=Performance(
            latency_sla_minutes=5, peak_throughput_msgs_sec=10, data_freshness="real-time", p95_latency_minutes=3
        ))
        candidate = {"service": "Cloud Storage Transfer Service", "estimated_cost": 100.0}  # batch-tier service

        results = validator.validate_service_candidate(candidate, req)

        gr_2_1 = _find(results, "GR 2.1")
        assert gr_2_1.status == GuardrailStatus.STOP
        assert "PRUNE" in gr_2_1.source

    def test_gr_2_1_passes_for_streaming_service_under_tight_sla(self, validator: GuardrailValidator):
        req = _requirement(performance=Performance(
            latency_sla_minutes=5, peak_throughput_msgs_sec=10, data_freshness="real-time", p95_latency_minutes=3
        ))
        candidate = {"service": "Pub/Sub", "estimated_cost": 100.0}
        results = validator.validate_service_candidate(candidate, req)
        assert _find(results, "GR 2.1").status == GuardrailStatus.PASS

    def test_scenario_budget_40_percent_over_needs_approval(self, cost_validator: CostValidator):
        """Named scenario: budget 40% over -> needs approval. The task's informal "FLAG for
        approval" wording maps to status=ESCALATE here (not FLAG), because FLAG is defined as
        "proceed without pausing" while this tier explicitly requires human approval before
        proceeding - see the GR 2.2 tiering table in guardrail_validator.py's module docstring.
        """
        result = cost_validator.validate_cost(total_cost=7000.0, budget_cap=5000.0)  # 40% over
        assert result.status == GuardrailStatus.ESCALATE
        assert result.severity == GuardrailSeverity.WARN
        assert "CAUTION" in result.source

    def test_gr_2_2_within_10_percent_is_flag_not_escalate(self, cost_validator: CostValidator):
        result = cost_validator.validate_cost(total_cost=5400.0, budget_cap=5000.0)  # 8% over
        assert result.status == GuardrailStatus.FLAG
        assert result.severity == GuardrailSeverity.WARN

    def test_gr_2_2_over_50_percent_escalates_to_cfo(self, cost_validator: CostValidator):
        result = cost_validator.validate_cost(total_cost=8000.0, budget_cap=5000.0)  # 60% over
        assert result.status == GuardrailStatus.ESCALATE
        assert result.severity == GuardrailSeverity.ERROR
        assert "CFO" in result.remediation

    def test_gr_2_2_within_budget_passes(self, cost_validator: CostValidator):
        result = cost_validator.validate_cost(total_cost=4000.0, budget_cap=5000.0)
        assert result.status == GuardrailStatus.PASS

    def test_gr_2_2_roi_justification_when_current_cost_known(self, cost_validator: CostValidator):
        result = cost_validator.validate_cost(total_cost=7000.0, budget_cap=5000.0, current_state_cost=12000.0)
        assert "ROI" in result.remediation

    def test_gr_2_3_compliance_gap_flags_for_security_review(
        self, validator: GuardrailValidator, rag_system: MagicMock
    ):
        rag_system.get_compliance_rules.return_value = {"regulation": "HIPAA", "requires_encryption": True}
        req = _requirement(compliance=Compliance(regulations=["HIPAA"], encryption=False))
        candidate = {"service": "Pub/Sub", "estimated_cost": 100.0}

        results = validator.validate_service_candidate(candidate, req)
        gr_2_3 = _find(results, "GR 2.3 Compliance Gap")
        assert gr_2_3.status == GuardrailStatus.FLAG
        assert "security review" in gr_2_3.remediation.lower()

    def test_gr_2_4_flags_known_incompatible_pair(self, validator: GuardrailValidator):
        req = _requirement()
        candidate = {"service": "Dataproc", "estimated_cost": 100.0, "selected_services": {"storage": "Firestore"}}
        results = validator.validate_service_candidate(candidate, req)
        gr_2_4 = _find(results, "GR 2.4")
        assert gr_2_4.status == GuardrailStatus.STOP

    def test_gr_2_5_flags_skill_gap_with_training_estimate(self, validator: GuardrailValidator):
        req = _requirement(team=Team(size=2, skills=["excel"]))
        candidate = {"service": "Kafka on GKE", "estimated_cost": 100.0}
        results = validator.validate_service_candidate(candidate, req)
        gr_2_5 = _find(results, "GR 2.5")
        assert gr_2_5.status == GuardrailStatus.FLAG
        assert "training" in gr_2_5.remediation.lower() or "hiring" in gr_2_5.remediation.lower()

    def test_gr_2_5_passes_when_team_has_relevant_skills(self, validator: GuardrailValidator):
        req = _requirement(team=Team(size=2, skills=["Kafka", "Kubernetes"]))
        candidate = {"service": "Kafka on GKE", "estimated_cost": 100.0}
        results = validator.validate_service_candidate(candidate, req)
        assert _find(results, "GR 2.5").status == GuardrailStatus.PASS


# === SET 3: Design Validation ===


class TestValidateDesign:
    def test_gr_3_1_full_coverage_passes(self, validator: GuardrailValidator):
        design = _design(_requirement())
        gr_3_1 = _find(validator.validate_design(design), "GR 3.1")
        assert gr_3_1.status == GuardrailStatus.PASS

    def test_gr_3_1_flags_incomplete_coverage(self, validator: GuardrailValidator):
        design = _design(_requirement(), cost_analysis=None, implementation_roadmap=None)
        gr_3_1 = _find(validator.validate_design(design), "GR 3.1")
        assert gr_3_1.status == GuardrailStatus.FLAG

    def test_scenario_compliance_gap_escalates_to_security(self, validator: GuardrailValidator, rag_system: MagicMock):
        """Named scenario: compliance gap -> ESCALATE to security (final-design stage)."""
        rag_system.get_compliance_rules.return_value = {"regulation": "HIPAA", "requires_encryption": True}
        req = _requirement(compliance=Compliance(regulations=["HIPAA"], encryption=False))
        design = _design(req)

        results = validator.validate_design(design)
        gr_3_3 = _find(results, "GR 3.3 Compliance Gap")
        assert gr_3_3.status == GuardrailStatus.ESCALATE
        assert gr_3_3.severity == GuardrailSeverity.ERROR

    def test_gr_3_5_flags_missing_dr_plan(self, validator: GuardrailValidator):
        design = _design(_requirement())
        gr_3_5 = _find(validator.validate_design(design), "GR 3.5")
        assert gr_3_5.status == GuardrailStatus.FLAG

    def test_gr_3_5_passes_when_dr_plan_present(self, validator: GuardrailValidator):
        design = _design(
            _requirement(),
            implementation_roadmap={
                "phases": [{"phase": 1, "name": "Ingestion", "service": "Pub/Sub"}],
                "disaster_recovery": "Multi-region failover with 15-minute RPO.",
            },
        )
        gr_3_5 = _find(validator.validate_design(design), "GR 3.5")
        assert gr_3_5.status == GuardrailStatus.PASS


# === SET 4: Behavioral ===


class TestValidateBehavior:
    def test_gr_4_1_flags_missing_reasoning(self, validator: GuardrailValidator):
        design = _design(_requirement(), decision_matrix={"selected_path": [], "reasoning": ""})
        gr_4_1 = _find(validator.validate_behavior(design), "GR 4.1")
        assert gr_4_1.status == GuardrailStatus.FLAG

    def test_scenario_hallucinated_pricing_flags_low_confidence(
        self, validator: GuardrailValidator, hallucination_detector: MagicMock
    ):
        """Named scenario: design claims $0.02/million messages (can't verify) -> flagged, confidence lowered."""
        hallucination_detector.detect_hallucinations.return_value = [
            Hallucination(
                claim="Pub/Sub costs $0.02 per million messages in this configuration",
                location="output.decision_matrix.reasoning",
                reason="This specific rate does not appear in the design's own cost_analysis data.",
                confidence=0.85,
            )
        ]
        design = _design(_requirement(), decision_matrix={
            "selected_path": ["Pub/Sub", "Dataflow", "BigQuery", "Looker Studio"],
            "final_score": 0.75,
            "reasoning": "Pub/Sub costs $0.02 per million messages, which is extremely cheap.",
        })

        results = validator.validate_behavior(design)

        gr_4_2 = _find(results, "GR 4.2 Hallucinated Claim")
        assert gr_4_2.status == GuardrailStatus.FLAG
        assert "$0.02" in gr_4_2.message

        gr_4_3 = _find(results, "GR 4.3")
        # base final_score 0.75 minus the hallucination penalty should drop below the 0.70 threshold.
        assert gr_4_3.status == GuardrailStatus.ESCALATE

    def test_gr_4_2_passes_with_no_hallucinations(self, validator: GuardrailValidator):
        design = _design(_requirement())
        gr_4_2 = _find(validator.validate_behavior(design), "GR 4.2 No Hallucinated")
        assert gr_4_2.status == GuardrailStatus.PASS

    def test_gr_4_3_passes_at_or_above_threshold(self, validator: GuardrailValidator):
        design = _design(_requirement(), decision_matrix={
            "selected_path": ["Pub/Sub"], "final_score": 0.9, "reasoning": "Solid choice."
        })
        gr_4_3 = _find(validator.validate_behavior(design), "GR 4.3")
        assert gr_4_3.status == GuardrailStatus.PASS

    def test_gr_4_4_notes_determinism_requires_rerun(self, validator: GuardrailValidator):
        gr_4_4 = _find(validator.validate_behavior(_design(_requirement())), "GR 4.4")
        assert gr_4_4.status == GuardrailStatus.PASS
        assert "check_determinism" in gr_4_4.message

    def test_check_determinism_passes_when_runs_agree(self, validator: GuardrailValidator):
        design = _design(_requirement())
        result = validator.check_determinism(_requirement(), design_fn=lambda r: design, runs=3)
        assert result.status == GuardrailStatus.PASS

    def test_check_determinism_flags_when_runs_disagree(self, validator: GuardrailValidator):
        req = _requirement()
        design_a = _design(req, decision_matrix={"selected_path": ["Pub/Sub", "Dataflow"], "reasoning": "a"})
        design_b = _design(req, decision_matrix={"selected_path": ["Kafka", "Dataproc"], "reasoning": "b"})
        outcomes = iter([design_a, design_b])

        result = validator.check_determinism(req, design_fn=lambda r: next(outcomes), runs=2)
        assert result.status == GuardrailStatus.FLAG

    def test_check_determinism_requires_at_least_two_runs(self, validator: GuardrailValidator):
        with pytest.raises(ValueError):
            validator.check_determinism(_requirement(), design_fn=lambda r: _design(_requirement()), runs=1)


# === ComplianceValidator (used directly, not just via GuardrailValidator) ===


class TestComplianceValidator:
    def test_supported_regulation_passes_when_controls_present(
        self, compliance_validator: ComplianceValidator, rag_system: MagicMock
    ):
        rag_system.get_compliance_rules.return_value = {"regulation": "SOC2", "requires_encryption": True}
        results = compliance_validator.check_compliance({"encryption": True}, ["SOC2"])
        assert results[0].status == GuardrailStatus.PASS

    def test_unsupported_regulation_is_flagged_not_raised(self, compliance_validator: ComplianceValidator):
        results = compliance_validator.check_compliance({}, ["MADE-UP-REG"])
        assert results[0].status == GuardrailStatus.FLAG
        assert results[0].severity == GuardrailSeverity.INFO

    def test_missing_rule_data_is_flagged(self, compliance_validator: ComplianceValidator, rag_system: MagicMock):
        rag_system.get_compliance_rules.return_value = {}
        results = compliance_validator.check_compliance({}, ["GDPR"])
        assert results[0].status == GuardrailStatus.FLAG

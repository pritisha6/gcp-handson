"""Unit tests for TreeOfThoughtEngine.

ThoughtGenerator and CriticEvaluator are mocked per the spec; DecisionMaker
is real, so its pruning/beam-selection logic is genuinely exercised against
the mocked critic scores.
"""
from typing import Any, Dict, List
from unittest.mock import MagicMock

import pytest

from app.agents.decision_maker import DecisionMaker
from app.schemas.tot import Candidate, EvalResult, ScoreBreakdown
from app.services.tot_engine import TreeOfThoughtEngine


def _candidate(service: str, cost: float = 1000.0, feasibility: float = 0.9) -> Dict[str, Any]:
    return {
        "service": service,
        "rationale": f"{service} fits this scenario",
        "estimated_cost": cost,
        "tradeoffs": ["example trade-off"],
        "feasibility": feasibility,
    }


def _eval_result(candidate: Dict[str, Any], latency=1.0, cost=1.0, ops=1.0, compliance=1.0) -> EvalResult:
    scores = ScoreBreakdown(latency=latency, cost=cost, ops=ops, compliance=compliance)
    final = round(0.30 * latency + 0.30 * cost + 0.25 * ops + 0.15 * compliance, 4)
    return EvalResult(
        candidate=Candidate.model_validate(candidate),
        scores=scores,
        final_score=final,
        reasoning=f"scored {candidate['service']}",
        confidence=1.0,
    )


@pytest.fixture
def state_manager() -> MagicMock:
    return MagicMock()


@pytest.fixture
def requirements() -> Dict[str, Any]:
    """Example scenario: 200K msgs/sec peak throughput, 15-minute SLA, $5K/month budget."""
    return {
        "data_sources": [{"name": "clickstream", "type": "Messaging", "size_gb": 500, "throughput_records_sec": 200000}],
        "performance": {
            "latency_sla_minutes": 15,
            "peak_throughput_msgs_sec": 200000,
            "data_freshness": "near-real-time",
            "p95_latency_minutes": 10,
        },
        "budget": {"monthly_cap_usd": 5000, "currency": "USD"},
        "team": {"size": 4, "skills": ["python", "dataflow", "kafka"]},
        "compliance": {"data_types": [], "regulations": [], "data_residency": None, "encryption": True},
        "context": None,
    }


def _make_engine(
    thought_generator: MagicMock,
    state_manager: MagicMock,
    critic_evaluator: MagicMock,
    beam_width: int = 3,
    confidence_threshold: float = 0.85,
    time_budget_seconds: float = 120.0,
) -> TreeOfThoughtEngine:
    decision_maker = DecisionMaker(critic_evaluator=critic_evaluator, beam_width=beam_width)
    return TreeOfThoughtEngine(
        thought_generator=thought_generator,
        decision_maker=decision_maker,
        state_manager=state_manager,
        beam_width=beam_width,
        confidence_threshold=confidence_threshold,
        time_budget_seconds=time_budget_seconds,
    )


def _uniform_good_setup(state_manager: MagicMock):
    """3 candidates per layer, all scoring perfectly -> a clean, unambiguous happy path."""
    thought_generator = MagicMock()
    layer_candidates = {
        "ingestion": [_candidate("Pub/Sub"), _candidate("Kafka on GKE"), _candidate("Cloud Storage Transfer")],
        "processing": [_candidate("Dataflow"), _candidate("Dataproc"), _candidate("Cloud Functions")],
        "storage": [_candidate("BigQuery"), _candidate("Cloud Storage"), _candidate("Firestore")],
        "serving": [_candidate("Looker Studio"), _candidate("BigQuery BI Engine"), _candidate("Cloud Run API")],
    }
    thought_generator.generate_candidates.side_effect = lambda requirements, layer: [
        Candidate.model_validate(c) for c in layer_candidates[layer]
    ]

    critic_evaluator = MagicMock()
    critic_evaluator.evaluate.side_effect = lambda candidate, requirements: _eval_result(candidate)

    return thought_generator, critic_evaluator


def test_search_completes_full_path_with_good_scores(state_manager, requirements):
    thought_generator, critic_evaluator = _uniform_good_setup(state_manager)
    engine = _make_engine(thought_generator, state_manager, critic_evaluator, confidence_threshold=0.5)

    result = engine.search(requirements)

    assert result["status"] == "completed"
    assert result["termination_reason"] == "confidence_threshold_met"
    assert len(result["architecture_path"]) == 4
    assert set(result["services"].keys()) == {"ingestion", "processing", "storage", "serving"}
    assert result["final_score"] == 1.0


def test_search_full_scenario_200k_msgs_15min_sla_5k_budget(state_manager, requirements):
    """End-to-end example scenario named in the spec: 200K msgs/sec, 15-min SLA, $5K budget."""
    thought_generator, critic_evaluator = _uniform_good_setup(state_manager)
    engine = _make_engine(thought_generator, state_manager, critic_evaluator, confidence_threshold=0.5)

    result = engine.search(requirements, design_id="scenario-200k")

    assert result["design_id"] == "scenario-200k"
    assert result["status"] == "completed"
    assert result["services"]["ingestion"] in {"Pub/Sub", "Kafka on GKE", "Cloud Storage Transfer"}
    assert " -> " in result["reasoning"]


def test_beam_width_limits_survivors_per_layer(state_manager, requirements):
    thought_generator, critic_evaluator = _uniform_good_setup(state_manager)
    engine = _make_engine(thought_generator, state_manager, critic_evaluator, beam_width=2, confidence_threshold=0.5)

    result = engine.search(requirements)

    # beam_width=2 means at most 1 alternative alongside the selected best path.
    assert len(result["alternatives"]) <= 1


def test_hard_failure_candidates_are_pruned(state_manager, requirements):
    thought_generator = MagicMock()
    thought_generator.generate_candidates.side_effect = lambda requirements, layer: [
        Candidate.model_validate(_candidate("Good Service")),
        Candidate.model_validate(_candidate("Bad Latency Service")),
    ]

    def fake_evaluate(candidate, requirements):
        if candidate["service"] == "Bad Latency Service":
            return _eval_result(candidate, latency=0.0)
        return _eval_result(candidate)

    critic_evaluator = MagicMock()
    critic_evaluator.evaluate.side_effect = fake_evaluate

    engine = _make_engine(thought_generator, state_manager, critic_evaluator, beam_width=3, confidence_threshold=0.5)
    result = engine.search(requirements)

    assert result["status"] == "completed"
    assert "Bad Latency Service" not in result["architecture_path"]
    assert all("Bad Latency Service" not in alt["path"] for alt in result["alternatives"])


def test_all_branches_pruned_escalates(state_manager, requirements):
    thought_generator = MagicMock()
    thought_generator.generate_candidates.side_effect = lambda requirements, layer: [
        Candidate.model_validate(_candidate("Non-compliant Service"))
    ]

    critic_evaluator = MagicMock()
    critic_evaluator.evaluate.side_effect = lambda candidate, requirements: _eval_result(candidate, compliance=0.0)

    engine = _make_engine(thought_generator, state_manager, critic_evaluator)
    result = engine.search(requirements)

    assert result["status"] == "escalated"
    assert result["termination_reason"] == "all_branches_pruned"
    assert result["architecture_path"] == []


def test_confidence_threshold_met_stops_with_that_reason(state_manager, requirements):
    thought_generator, critic_evaluator = _uniform_good_setup(state_manager)
    engine = _make_engine(thought_generator, state_manager, critic_evaluator, confidence_threshold=0.1)

    result = engine.search(requirements)

    assert result["status"] == "completed"
    assert result["termination_reason"] == "confidence_threshold_met"


def test_depth_limit_reached_when_confidence_threshold_not_met(state_manager, requirements):
    thought_generator = MagicMock()
    thought_generator.generate_candidates.side_effect = lambda requirements, layer: [
        Candidate.model_validate(_candidate("Mediocre Service"))
    ]

    critic_evaluator = MagicMock()
    critic_evaluator.evaluate.side_effect = lambda candidate, requirements: _eval_result(
        candidate, latency=0.5, cost=0.5, ops=0.5, compliance=0.5
    )

    engine = _make_engine(thought_generator, state_manager, critic_evaluator, confidence_threshold=0.99)
    result = engine.search(requirements)

    assert result["status"] == "completed"
    assert result["termination_reason"] == "depth_limit_reached"
    assert len(result["architecture_path"]) == 4


def test_time_budget_exceeded_returns_partial_result(state_manager, requirements, monkeypatch):
    """A 0.0s wall-clock budget is flaky to test directly (clock resolution can
    make elapsed time read as exactly 0.0 across a fast, fully-mocked run), so
    time.monotonic() is patched to deterministically report the budget as
    already exceeded on the very first check.
    """
    thought_generator, critic_evaluator = _uniform_good_setup(state_manager)
    engine = _make_engine(
        thought_generator, state_manager, critic_evaluator, confidence_threshold=0.99, time_budget_seconds=10.0
    )

    call_count = {"n": 0}

    def fake_monotonic():
        call_count["n"] += 1
        return 0.0 if call_count["n"] == 1 else 999.0  # call 1 = start_time; every check after is "expired"

    monkeypatch.setattr("app.services.tot_engine.time.monotonic", fake_monotonic)

    result = engine.search(requirements)

    assert result["status"] == "partial"
    assert result["termination_reason"] == "time_budget_exceeded"
    assert result["architecture_path"] == []


def test_thought_generator_failure_for_one_path_does_not_crash_others(state_manager, requirements):
    thought_generator = MagicMock()

    def flaky_generate(requirements, layer):
        if layer == "processing":
            raise RuntimeError("Claude timed out")
        return [Candidate.model_validate(_candidate(f"{layer}-service"))]

    thought_generator.generate_candidates.side_effect = flaky_generate

    critic_evaluator = MagicMock()
    critic_evaluator.evaluate.side_effect = lambda candidate, requirements: _eval_result(candidate)

    engine = _make_engine(thought_generator, state_manager, critic_evaluator)
    result = engine.search(requirements)

    # Every path fails to produce processing-layer candidates -> escalation at that layer.
    assert result["status"] == "escalated"


def test_decision_trail_is_recorded_across_layers(state_manager, requirements):
    thought_generator, critic_evaluator = _uniform_good_setup(state_manager)
    decision_maker = DecisionMaker(critic_evaluator=critic_evaluator, beam_width=3)
    engine = TreeOfThoughtEngine(
        thought_generator=thought_generator,
        decision_maker=decision_maker,
        state_manager=state_manager,
        confidence_threshold=0.5,
    )

    engine.search(requirements)

    trail = decision_maker.get_decision_trail()
    # One make_decision call per surviving parent path per layer: 1 for the
    # root at "ingestion", then up to beam_width per layer after that.
    levels_seen_in_order = []
    for entry in trail:
        if entry["level"] not in levels_seen_in_order:
            levels_seen_in_order.append(entry["level"])
    assert levels_seen_in_order == ["ingestion", "processing", "storage", "serving"]
    assert len(trail) >= 4
    assert all(entry["selected"] is not None for entry in trail)

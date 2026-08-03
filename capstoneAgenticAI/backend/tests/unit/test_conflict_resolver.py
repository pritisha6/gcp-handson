"""Unit tests for ConflictResolver."""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.config import Settings
from app.schemas.conflict import ConflictSeverity
from app.schemas.design import Requirement
from app.services.conflict_resolver import ConflictResolver


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """Skip tenacity's real backoff sleeps so failure-path tests stay fast."""
    monkeypatch.setattr("time.sleep", lambda seconds: None)


@pytest.fixture
def settings() -> Settings:
    return Settings(GROQ_API_KEY="k", GCP_PROJECT_ID="p", PINECONE_API_KEY="k")


@pytest.fixture
def groq_client() -> MagicMock:
    return MagicMock()


@pytest.fixture
def resolver(groq_client: MagicMock, settings: Settings) -> ConflictResolver:
    return ConflictResolver(client=groq_client, settings=settings)


def _requirement(**overrides) -> Requirement:
    base = {
        "data_sources": [{"name": "orders_db", "type": "DB", "size_gb": 10, "throughput_records_sec": 5}],
        "performance": {
            "latency_sla_minutes": 60,
            "peak_throughput_msgs_sec": 10,
            "data_freshness": "daily",
            "p95_latency_minutes": 45,
        },
        "budget": {"monthly_cap_usd": 5000, "currency": "USD"},
        "team": {"size": 3, "skills": ["python", "dataflow"]},
        "compliance": {"data_types": [], "regulations": [], "data_residency": None, "encryption": True},
        "context": None,
    }
    for key, value in overrides.items():
        if isinstance(base.get(key), dict) and isinstance(value, dict):
            base[key] = {**base[key], **value}
        else:
            base[key] = value
    return Requirement.model_validate(base)


def _fake_resolution_response(resolutions: list):
    tool_call = SimpleNamespace(
        function=SimpleNamespace(
            name="record_resolutions", arguments=json.dumps({"resolutions": resolutions})
        ),
        id="call_1",
    )
    message = SimpleNamespace(tool_calls=[tool_call])
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message)],
        usage=SimpleNamespace(prompt_tokens=50, completion_tokens=20),
    )


def test_no_conflicts_for_well_formed_requirement(resolver, groq_client):
    req = _requirement()

    conflicts = resolver.detect_conflicts(req)

    assert conflicts == []
    groq_client.chat.completions.create.assert_not_called()


def test_detects_latency_vs_freshness_conflict(resolver, groq_client):
    groq_client.chat.completions.create.side_effect = RuntimeError("no network in this test")
    req = _requirement(performance={"latency_sla_minutes": 5, "data_freshness": "daily"})

    conflicts = resolver.detect_conflicts(req)

    match = next(c for c in conflicts if c.type == "latency_vs_freshness")
    assert match.severity == ConflictSeverity.ERROR
    assert "performance.latency_sla_minutes" in match.fields_involved
    assert "performance.data_freshness" in match.fields_involved
    assert match.suggested_resolution  # static fallback used since the Groq call failed


def test_detects_budget_vs_throughput_conflict(resolver, groq_client):
    groq_client.chat.completions.create.side_effect = RuntimeError("no network in this test")
    req = _requirement(
        performance={"peak_throughput_msgs_sec": 5000}, budget={"monthly_cap_usd": 200, "currency": "USD"}
    )

    conflicts = resolver.detect_conflicts(req)

    assert any(c.type == "budget_vs_throughput" and c.severity == ConflictSeverity.ERROR for c in conflicts)


def test_detects_team_skills_vs_complexity_conflict(resolver, groq_client):
    groq_client.chat.completions.create.side_effect = RuntimeError("no network in this test")
    req = _requirement(
        data_sources=[{"name": "events", "type": "Messaging", "size_gb": 5, "throughput_records_sec": 20}],
        team={"size": 2, "skills": ["excel"]},
    )

    conflicts = resolver.detect_conflicts(req)

    assert any(c.type == "team_skills_vs_complexity" and c.severity == ConflictSeverity.WARNING for c in conflicts)


def test_no_team_skills_conflict_when_relevant_skill_present(resolver, groq_client):
    req = _requirement(
        data_sources=[{"name": "events", "type": "Messaging", "size_gb": 5, "throughput_records_sec": 20}],
        team={"size": 2, "skills": ["Apache Kafka", "Python"]},
    )

    conflicts = resolver.detect_conflicts(req)

    assert not any(c.type == "team_skills_vs_complexity" for c in conflicts)
    groq_client.chat.completions.create.assert_not_called()


def test_detects_freshness_vs_cost_conflict(resolver, groq_client):
    groq_client.chat.completions.create.side_effect = RuntimeError("no network in this test")
    req = _requirement(
        performance={"data_freshness": "real-time"}, budget={"monthly_cap_usd": 100, "currency": "USD"}
    )

    conflicts = resolver.detect_conflicts(req)

    assert any(c.type == "freshness_vs_cost" and c.severity == ConflictSeverity.WARNING for c in conflicts)


def test_conflicts_sorted_errors_before_warnings(resolver, groq_client):
    groq_client.chat.completions.create.side_effect = RuntimeError("no network in this test")
    req = _requirement(
        performance={"latency_sla_minutes": 5, "data_freshness": "real-time", "peak_throughput_msgs_sec": 5000},
        budget={"monthly_cap_usd": 100, "currency": "USD"},
        team={"size": 1, "skills": []},
        data_sources=[{"name": "events", "type": "Messaging", "size_gb": 5, "throughput_records_sec": 20}],
    )

    conflicts = resolver.detect_conflicts(req)

    severities = [c.severity for c in conflicts]
    assert len(severities) >= 2
    first_warning_index = next(
        (i for i, s in enumerate(severities) if s == ConflictSeverity.WARNING), len(severities)
    )
    assert all(s == ConflictSeverity.ERROR for s in severities[:first_warning_index])


def test_groq_enrichment_overrides_static_resolution(resolver, groq_client):
    groq_client.chat.completions.create.return_value = _fake_resolution_response(
        [{"type": "latency_vs_freshness", "suggested_resolution": "Custom Groq-generated advice."}]
    )
    req = _requirement(performance={"latency_sla_minutes": 5, "data_freshness": "daily"})

    conflicts = resolver.detect_conflicts(req)

    match = next(c for c in conflicts if c.type == "latency_vs_freshness")
    assert match.suggested_resolution == "Custom Groq-generated advice."


def test_groq_enrichment_failure_falls_back_to_static_resolution(resolver, groq_client):
    groq_client.chat.completions.create.side_effect = RuntimeError("service unavailable")
    req = _requirement(performance={"latency_sla_minutes": 5, "data_freshness": "daily"})

    conflicts = resolver.detect_conflicts(req)

    match = next(c for c in conflicts if c.type == "latency_vs_freshness")
    assert "streaming architecture" in match.suggested_resolution

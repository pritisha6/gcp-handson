"""Unit tests for RequirementExtractor."""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.config import Settings
from app.schemas.design import Requirement
from app.services.requirement_extractor import RequirementExtractor
from app.utils.errors import ExtractionError


@pytest.fixture
def settings() -> Settings:
    return Settings(GROQ_API_KEY="k", GCP_PROJECT_ID="p", PINECONE_API_KEY="k")


@pytest.fixture
def groq_client() -> MagicMock:
    return MagicMock()


@pytest.fixture
def extractor(groq_client: MagicMock, settings: Settings) -> RequirementExtractor:
    return RequirementExtractor(client=groq_client, settings=settings)


def _fake_response(tool_input: dict, input_tokens: int = 100, output_tokens: int = 50):
    tool_call = SimpleNamespace(
        function=SimpleNamespace(name="record_requirements", arguments=json.dumps(tool_input)),
        id="call_1",
    )
    message = SimpleNamespace(tool_calls=[tool_call])
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message)],
        usage=SimpleNamespace(prompt_tokens=input_tokens, completion_tokens=output_tokens),
    )


_COMPLETE_TOOL_INPUT = {
    "data_sources": [{"name": "orders_db", "type": "DB", "size_gb": 120, "throughput_records_sec": 50}],
    "performance": {
        "latency_sla_minutes": 30,
        "peak_throughput_msgs_sec": 100,
        "data_freshness": "hourly",
        "p95_latency_minutes": 20,
    },
    "budget": {"monthly_cap_usd": 5000, "currency": "USD"},
    "team": {"size": 4, "skills": ["python", "sql"]},
    "compliance": {"data_types": ["PII"], "regulations": ["GDPR"], "data_residency": "EU", "encryption": True},
    "context": {
        "current_system": "legacy on-prem ETL",
        "migration_approach": "redesign",
        "known_constraints": "must run in EU region",
        "priorities": ["cost", "reliability"],
    },
    "extraction_notes": [],
}


def test_extract_requirements_returns_valid_requirement(extractor, groq_client):
    groq_client.chat.completions.create.return_value = _fake_response(_COMPLETE_TOOL_INPUT)

    result = extractor.extract_requirements(["Some document text about orders_db..."])

    assert isinstance(result, Requirement)
    assert result.data_sources[0].name == "orders_db"
    assert result.data_sources[0].type.value == "DB"
    assert result.performance.data_freshness == "hourly"
    assert result.budget.monthly_cap_usd == 5000
    assert result.team.size == 4
    assert "python" in result.team.skills
    assert result.compliance.data_residency == "EU"
    assert result.compliance.encryption is True
    assert "Current system: legacy on-prem ETL" in result.context
    assert "Migration approach: redesign" in result.context
    assert "Stakeholder priorities: cost, reliability" in result.context


def test_extract_requirements_records_api_cost(extractor, groq_client):
    from app.utils.api_cost_tracker import api_cost_tracker

    groq_client.chat.completions.create.return_value = _fake_response(_COMPLETE_TOOL_INPUT, 111, 22)
    before = api_cost_tracker.summary().get("groq", {}).get("calls", 0)

    extractor.extract_requirements(["doc"])

    after = api_cost_tracker.summary()["groq"]["calls"]
    assert after == before + 1


def test_extract_requirements_with_warnings_returns_no_warnings_for_complete_data(extractor, groq_client):
    groq_client.chat.completions.create.return_value = _fake_response(_COMPLETE_TOOL_INPUT)

    _, warnings = extractor.extract_requirements_with_warnings(["doc"])

    assert warnings == []


def test_extract_requirements_fills_defaults_for_missing_fields(extractor, groq_client):
    incomplete_input = {"data_sources": [], "performance": {}, "budget": {}, "team": {}, "compliance": {}}
    groq_client.chat.completions.create.return_value = _fake_response(incomplete_input)

    requirement, warnings = extractor.extract_requirements_with_warnings(["ambiguous doc"])

    assert isinstance(requirement, Requirement)
    assert len(requirement.data_sources) == 1
    assert requirement.data_sources[0].name == "Unknown source"
    assert requirement.team.size == 1
    assert requirement.performance.data_freshness == "daily"
    assert len(warnings) > 0
    assert any("data source" in w.lower() for w in warnings)
    assert any("team.size" in w for w in warnings)


def test_extract_requirements_invalid_data_source_type_defaults_to_db(extractor, groq_client):
    tool_input = {**_COMPLETE_TOOL_INPUT, "data_sources": [{"name": "queue", "type": "Bogus"}]}
    groq_client.chat.completions.create.return_value = _fake_response(tool_input)

    requirement, warnings = extractor.extract_requirements_with_warnings(["doc"])

    assert requirement.data_sources[0].type.value == "DB"
    assert any("invalid type" in w.lower() for w in warnings)


def test_extract_requirements_raises_for_empty_documents(extractor):
    with pytest.raises(ExtractionError):
        extractor.extract_requirements([])


def test_extract_requirements_raises_for_blank_documents(extractor):
    with pytest.raises(ExtractionError):
        extractor.extract_requirements(["   ", "\n"])


def test_extract_requirements_raises_when_no_tool_use_returned(extractor, groq_client):
    groq_client.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[]))],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
    )

    with pytest.raises(ExtractionError):
        extractor.extract_requirements(["doc"])


def test_extract_requirements_wraps_groq_failure_as_extraction_error(extractor):
    extractor._call_groq_raw = MagicMock(side_effect=RuntimeError("network error"))

    with pytest.raises(ExtractionError):
        extractor.extract_requirements(["doc"])

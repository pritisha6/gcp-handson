"""Extracts structured ETL requirements from source documents using Claude."""
from typing import Any, Dict, List, Optional, Tuple

from anthropic import Anthropic
from pydantic import ValidationError
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import Settings, get_settings
from app.schemas.design import Requirement
from app.utils.api_cost_tracker import api_cost_tracker
from app.utils.errors import ExtractionError
from app.utils.logger import get_logger

logger = get_logger(__name__)

_VALID_DATA_SOURCE_TYPES = {"DB", "API", "File", "Messaging"}

_SYSTEM_PROMPT = """You are an ETL architecture requirements analyst. Your job is to \
read source documents (design docs, specs, meeting notes, spreadsheets) and extract a \
structured set of ETL pipeline requirements.

Extract:
- data_sources: each upstream system's name, type (DB/API/File/Messaging), approximate \
size in GB, and throughput in records/second.
- performance: latency SLA (minutes), peak throughput (messages/second), data freshness \
requirement, and p95 latency (minutes).
- budget: maximum acceptable monthly cost in USD.
- team: number of engineers and their relevant skills.
- compliance: data types handled (e.g. PII, PHI), applicable regulations (e.g. GDPR, \
HIPAA), required data residency region, and whether encryption is required.
- context: a description of the current system, the intended migration approach \
(lift-and-shift/redesign/hybrid), known constraints, and stakeholder priorities.

If a field is not mentioned in the documents, use a reasonable conservative default and \
add a note to extraction_notes explaining what was missing or ambiguous. Never fabricate \
specific numbers that aren't grounded in the source text; prefer a round, clearly \
conservative estimate and flag it in extraction_notes instead.

Always respond by calling the record_requirements tool with your findings."""

_EXTRACTION_TOOL = {
    "name": "record_requirements",
    "description": "Record the structured ETL pipeline requirements extracted from the source documents.",
    "input_schema": {
        "type": "object",
        "properties": {
            "data_sources": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "type": {"type": "string", "enum": sorted(_VALID_DATA_SOURCE_TYPES)},
                        "size_gb": {"type": "number"},
                        "throughput_records_sec": {"type": "number"},
                    },
                    "required": ["name", "type"],
                },
            },
            "performance": {
                "type": "object",
                "properties": {
                    "latency_sla_minutes": {"type": "number"},
                    "peak_throughput_msgs_sec": {"type": "number"},
                    "data_freshness": {"type": "string"},
                    "p95_latency_minutes": {"type": "number"},
                },
            },
            "budget": {
                "type": "object",
                "properties": {
                    "monthly_cap_usd": {"type": "number"},
                    "currency": {"type": "string"},
                },
            },
            "team": {
                "type": "object",
                "properties": {
                    "size": {"type": "integer"},
                    "skills": {"type": "array", "items": {"type": "string"}},
                },
            },
            "compliance": {
                "type": "object",
                "properties": {
                    "data_types": {"type": "array", "items": {"type": "string"}},
                    "regulations": {"type": "array", "items": {"type": "string"}},
                    "data_residency": {"type": "string"},
                    "encryption": {"type": "boolean"},
                },
            },
            "context": {
                "type": "object",
                "properties": {
                    "current_system": {"type": "string"},
                    "migration_approach": {"type": "string"},
                    "known_constraints": {"type": "string"},
                    "priorities": {"type": "array", "items": {"type": "string"}},
                },
            },
            "extraction_notes": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Notes about fields missing, ambiguous, or inferred rather than explicit.",
            },
        },
        "required": ["data_sources", "performance", "budget", "team", "compliance"],
    },
}


class RequirementExtractor:
    """Extracts a structured ``Requirement`` from raw document text via Claude."""

    def __init__(self, client: Optional[Anthropic] = None, settings: Optional[Settings] = None) -> None:
        self._settings = settings or get_settings()
        self._client = client or Anthropic(api_key=self._settings.CLAUDE_API_KEY)

    def extract_requirements(self, documents: List[str]) -> Requirement:
        """Extract a validated ``Requirement`` from raw document text.

        Args:
            documents: Raw text segments (e.g. document chunk texts) to analyze.

        Returns:
            A schema-valid Requirement. Missing/ambiguous fields are filled
            with conservative defaults; details are logged as warnings.

        Raises:
            ExtractionError: If Claude cannot be reached or returns unusable data.
        """
        requirement, _warnings = self.extract_requirements_with_warnings(documents)
        return requirement

    def extract_requirements_with_warnings(self, documents: List[str]) -> Tuple[Requirement, List[str]]:
        """Same as ``extract_requirements`` but also returns the extraction warnings.

        Args:
            documents: Raw text segments to analyze.

        Returns:
            A tuple of (Requirement, warnings), where warnings describes any
            fields that were missing, ambiguous, or defaulted.

        Raises:
            ExtractionError: If Claude cannot be reached or returns unusable data.
        """
        if not documents:
            raise ExtractionError("No documents were provided for requirement extraction.")

        document_text = self._prepare_input(documents)
        raw = self._call_claude(document_text)
        return self._to_requirement(raw)

    def _prepare_input(self, documents: List[str]) -> str:
        joined = "\n\n---\n\n".join(doc.strip() for doc in documents if doc and doc.strip())
        if not joined:
            raise ExtractionError("All provided documents were empty.")
        return joined

    @retry(reraise=True, stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=30))
    def _call_claude_raw(self, document_text: str):
        return self._client.messages.create(
            model=self._settings.CLAUDE_MODEL,
            max_tokens=4096,
            system=_SYSTEM_PROMPT,
            tools=[_EXTRACTION_TOOL],
            tool_choice={"type": "tool", "name": "record_requirements"},
            messages=[{"role": "user", "content": document_text}],
        )

    def _call_claude(self, document_text: str) -> Dict[str, Any]:
        try:
            response = self._call_claude_raw(document_text)
        except Exception as exc:
            logger.exception("Claude API call failed during requirement extraction")
            raise ExtractionError(f"Claude API call failed: {exc}") from exc

        usage = getattr(response, "usage", None)
        api_cost_tracker.record_call(
            "claude",
            input_tokens=getattr(usage, "input_tokens", 0) if usage else 0,
            output_tokens=getattr(usage, "output_tokens", 0) if usage else 0,
        )

        tool_use = next((block for block in response.content if block.type == "tool_use"), None)
        if tool_use is None:
            raise ExtractionError("Claude did not return a structured tool_use response.")
        return tool_use.input

    def _as_number(self, value: Any, default: float, field: str, warnings: List[str]) -> float:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
        warnings.append(f"'{field}' was missing or not numeric; defaulted to {default}.")
        return default

    def _to_requirement(self, raw: Dict[str, Any]) -> Tuple[Requirement, List[str]]:
        warnings: List[str] = list(raw.get("extraction_notes") or [])

        data_sources_raw = raw.get("data_sources") or []
        if not data_sources_raw:
            warnings.append("No data sources were found; inserted a placeholder entry.")
            data_sources_raw = [
                {"name": "Unknown source", "type": "DB", "size_gb": 0, "throughput_records_sec": 0}
            ]
        data_sources = []
        for ds in data_sources_raw:
            ds_type = ds.get("type") if ds.get("type") in _VALID_DATA_SOURCE_TYPES else "DB"
            if ds.get("type") not in _VALID_DATA_SOURCE_TYPES:
                warnings.append(f"Data source '{ds.get('name', '?')}' had an invalid type; defaulted to 'DB'.")
            data_sources.append(
                {
                    "name": ds.get("name") or "Unknown source",
                    "type": ds_type,
                    "size_gb": self._as_number(ds.get("size_gb"), 0.0, "data_sources.size_gb", warnings),
                    "throughput_records_sec": self._as_number(
                        ds.get("throughput_records_sec"), 0.0, "data_sources.throughput_records_sec", warnings
                    ),
                }
            )

        performance_raw = raw.get("performance") or {}
        data_freshness = performance_raw.get("data_freshness")
        if not data_freshness:
            data_freshness = "daily"
            warnings.append("'performance.data_freshness' was missing; defaulted to 'daily'.")
        performance = {
            "latency_sla_minutes": self._as_number(
                performance_raw.get("latency_sla_minutes"), 60.0, "performance.latency_sla_minutes", warnings
            ),
            "peak_throughput_msgs_sec": self._as_number(
                performance_raw.get("peak_throughput_msgs_sec"),
                0.0,
                "performance.peak_throughput_msgs_sec",
                warnings,
            ),
            "data_freshness": data_freshness,
            "p95_latency_minutes": self._as_number(
                performance_raw.get("p95_latency_minutes"), 60.0, "performance.p95_latency_minutes", warnings
            ),
        }

        budget_raw = raw.get("budget") or {}
        budget = {
            "monthly_cap_usd": self._as_number(
                budget_raw.get("monthly_cap_usd"), 0.0, "budget.monthly_cap_usd", warnings
            ),
            "currency": budget_raw.get("currency") or "USD",
        }

        team_raw = raw.get("team") or {}
        team_size = team_raw.get("size")
        if not (isinstance(team_size, (int, float)) and team_size >= 1):
            warnings.append("'team.size' was missing or invalid; defaulted to 1.")
            team_size = 1
        team = {"size": int(team_size), "skills": team_raw.get("skills") or []}

        compliance_raw = raw.get("compliance") or {}
        compliance = {
            "data_types": compliance_raw.get("data_types") or [],
            "regulations": compliance_raw.get("regulations") or [],
            "data_residency": compliance_raw.get("data_residency") or None,
            "encryption": bool(compliance_raw.get("encryption", True)),
        }

        context_raw = raw.get("context") or {}
        context_parts = []
        if context_raw.get("current_system"):
            context_parts.append(f"Current system: {context_raw['current_system']}")
        if context_raw.get("migration_approach"):
            context_parts.append(f"Migration approach: {context_raw['migration_approach']}")
        if context_raw.get("known_constraints"):
            context_parts.append(f"Known constraints: {context_raw['known_constraints']}")
        priorities = context_raw.get("priorities") or []
        if priorities:
            context_parts.append(f"Stakeholder priorities: {', '.join(priorities)}")
        context = "\n".join(context_parts) or None

        try:
            requirement = Requirement.model_validate(
                {
                    "data_sources": data_sources,
                    "performance": performance,
                    "budget": budget,
                    "team": team,
                    "compliance": compliance,
                    "context": context,
                }
            )
        except ValidationError as exc:
            logger.error("Extracted requirement failed schema validation: %s", exc)
            raise ExtractionError(
                "Extracted data did not match the Requirement schema.", {"errors": exc.errors()}
            ) from exc

        for warning in warnings:
            logger.warning("Requirement extraction warning: %s", warning)

        return requirement, warnings


_requirement_extractor: Optional[RequirementExtractor] = None


def get_requirement_extractor() -> RequirementExtractor:
    """Return a process-wide singleton RequirementExtractor (FastAPI dependency)."""
    global _requirement_extractor
    if _requirement_extractor is None:
        _requirement_extractor = RequirementExtractor()
    return _requirement_extractor

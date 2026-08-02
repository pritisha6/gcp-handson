"""Detects contradictions between requirement fields and suggests resolutions."""
from typing import List, Optional

from anthropic import Anthropic
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import Settings, get_settings
from app.schemas.conflict import Conflict, ConflictSeverity
from app.schemas.design import Requirement
from app.utils.api_cost_tracker import api_cost_tracker
from app.utils.logger import get_logger

logger = get_logger(__name__)

_LOW_LATENCY_THRESHOLD_MINUTES = 15
_BATCH_FRESHNESS_VALUES = {"daily", "hourly", "batch"}
_HIGH_THROUGHPUT_MSGS_SEC = 1000
_LOW_BUDGET_FOR_HIGH_THROUGHPUT_USD = 1000
_COMPLEX_SKILL_KEYWORDS = {
    "kafka",
    "dataflow",
    "spark",
    "streaming",
    "kubernetes",
    "pubsub",
    "pub/sub",
    "airflow",
    "beam",
}
_LOW_BUDGET_FOR_REALTIME_USD = 2000
_REALTIME_FRESHNESS_VALUES = {"real-time", "realtime", "near-real-time"}

_STATIC_RESOLUTIONS = {
    "latency_vs_freshness": (
        "Either relax the latency SLA to match a batch cadence, or switch the pipeline to a "
        "streaming architecture (e.g. Pub/Sub + Dataflow) that can meet the tighter SLA."
    ),
    "budget_vs_throughput": (
        "Increase the monthly budget cap, reduce the expected throughput, or choose a more "
        "cost-efficient ingestion path (e.g. batching small messages, using Pub/Sub Lite)."
    ),
    "team_skills_vs_complexity": (
        "Invest in training or hire for the missing skills, or choose more fully-managed GCP "
        "services (e.g. Dataflow templates) that reduce the operational burden on the team."
    ),
    "freshness_vs_cost": (
        "Relax the freshness requirement to a near-real-time or micro-batch cadence, or "
        "increase the budget to accommodate a streaming architecture."
    ),
}

_RESOLUTION_SYSTEM_PROMPT = """You are an ETL architecture requirements analyst. You will be given a \
summary of ETL pipeline requirements and a list of detected contradictions between requirement \
fields. For each conflict, write a concise (1-3 sentence), specific, actionable resolution \
suggestion tailored to the requirement values given, using the record_resolutions tool."""

_RESOLUTION_TOOL = {
    "name": "record_resolutions",
    "description": "Record refined, context-aware resolution suggestions for each detected conflict.",
    "input_schema": {
        "type": "object",
        "properties": {
            "resolutions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string"},
                        "suggested_resolution": {"type": "string"},
                    },
                    "required": ["type", "suggested_resolution"],
                },
            }
        },
        "required": ["resolutions"],
    },
}


class ConflictResolver:
    """Detects contradictions among a Requirement's fields and suggests resolutions."""

    def __init__(self, client: Optional[Anthropic] = None, settings: Optional[Settings] = None) -> None:
        self._settings = settings or get_settings()
        self._client = client or Anthropic(api_key=self._settings.CLAUDE_API_KEY)

    def detect_conflicts(self, requirements: Requirement) -> List[Conflict]:
        """Detect contradictions among a Requirement's fields.

        Args:
            requirements: The requirement to analyze.

        Returns:
            Detected conflicts, most severe first. Suggested resolutions are
            enriched via Claude when possible, falling back to a static
            per-type suggestion if that call fails.
        """
        conflicts = [
            c
            for c in (
                self._check_latency_vs_freshness(requirements),
                self._check_budget_vs_throughput(requirements),
                self._check_team_skills_vs_complexity(requirements),
                self._check_freshness_vs_cost(requirements),
            )
            if c is not None
        ]

        if conflicts:
            conflicts = self._enrich_with_claude(requirements, conflicts)

        severity_order = {ConflictSeverity.ERROR: 0, ConflictSeverity.WARNING: 1, ConflictSeverity.INFO: 2}
        conflicts.sort(key=lambda c: severity_order[c.severity])
        return conflicts

    # --- Rule-based detectors ---

    def _check_latency_vs_freshness(self, req: Requirement) -> Optional[Conflict]:
        freshness = req.performance.data_freshness.strip().lower()
        if (
            req.performance.latency_sla_minutes <= _LOW_LATENCY_THRESHOLD_MINUTES
            and freshness in _BATCH_FRESHNESS_VALUES
        ):
            return Conflict(
                type="latency_vs_freshness",
                severity=ConflictSeverity.ERROR,
                fields_involved=["performance.latency_sla_minutes", "performance.data_freshness"],
                description=(
                    f"The latency SLA of {req.performance.latency_sla_minutes} minutes is incompatible "
                    f"with a '{req.performance.data_freshness}' (batch) freshness requirement."
                ),
                suggested_resolution=_STATIC_RESOLUTIONS["latency_vs_freshness"],
            )
        return None

    def _check_budget_vs_throughput(self, req: Requirement) -> Optional[Conflict]:
        if (
            req.performance.peak_throughput_msgs_sec >= _HIGH_THROUGHPUT_MSGS_SEC
            and req.budget.monthly_cap_usd < _LOW_BUDGET_FOR_HIGH_THROUGHPUT_USD
        ):
            return Conflict(
                type="budget_vs_throughput",
                severity=ConflictSeverity.ERROR,
                fields_involved=["budget.monthly_cap_usd", "performance.peak_throughput_msgs_sec"],
                description=(
                    f"A peak throughput of {req.performance.peak_throughput_msgs_sec} msgs/sec is unlikely "
                    f"to fit within a ${req.budget.monthly_cap_usd:,.0f}/month budget."
                ),
                suggested_resolution=_STATIC_RESOLUTIONS["budget_vs_throughput"],
            )
        return None

    def _check_team_skills_vs_complexity(self, req: Requirement) -> Optional[Conflict]:
        needs_complex_services = (
            any(ds.type.value == "Messaging" for ds in req.data_sources)
            or req.performance.peak_throughput_msgs_sec >= _HIGH_THROUGHPUT_MSGS_SEC
        )
        skills = {s.strip().lower() for s in req.team.skills}
        has_relevant_skill = any(any(kw in skill for kw in _COMPLEX_SKILL_KEYWORDS) for skill in skills)

        if needs_complex_services and not has_relevant_skill:
            return Conflict(
                type="team_skills_vs_complexity",
                severity=ConflictSeverity.WARNING,
                fields_involved=["team.skills", "data_sources", "performance.peak_throughput_msgs_sec"],
                description=(
                    "The pipeline appears to require streaming/complex managed services, but the team's "
                    "listed skills don't include relevant experience (e.g. Kafka, Dataflow, Spark)."
                ),
                suggested_resolution=_STATIC_RESOLUTIONS["team_skills_vs_complexity"],
            )
        return None

    def _check_freshness_vs_cost(self, req: Requirement) -> Optional[Conflict]:
        freshness = req.performance.data_freshness.strip().lower()
        if freshness in _REALTIME_FRESHNESS_VALUES and req.budget.monthly_cap_usd < _LOW_BUDGET_FOR_REALTIME_USD:
            return Conflict(
                type="freshness_vs_cost",
                severity=ConflictSeverity.WARNING,
                fields_involved=["performance.data_freshness", "budget.monthly_cap_usd"],
                description=(
                    f"Real-time data freshness typically costs more than a ${req.budget.monthly_cap_usd:,.0f}"
                    "/month budget can support."
                ),
                suggested_resolution=_STATIC_RESOLUTIONS["freshness_vs_cost"],
            )
        return None

    # --- Claude-assisted resolution enrichment ---

    def _summarize_requirements(self, req: Requirement) -> str:
        return (
            f"Data sources: {', '.join(f'{ds.name} ({ds.type.value})' for ds in req.data_sources)}\n"
            f"Latency SLA: {req.performance.latency_sla_minutes} min, "
            f"Peak throughput: {req.performance.peak_throughput_msgs_sec} msgs/sec, "
            f"Freshness: {req.performance.data_freshness}\n"
            f"Budget cap: ${req.budget.monthly_cap_usd:,.0f}/month\n"
            f"Team size: {req.team.size}, skills: {', '.join(req.team.skills) or 'none listed'}"
        )

    @retry(reraise=True, stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=20))
    def _call_claude_raw(self, prompt: str):
        return self._client.messages.create(
            model=self._settings.CLAUDE_MODEL,
            max_tokens=2048,
            system=_RESOLUTION_SYSTEM_PROMPT,
            tools=[_RESOLUTION_TOOL],
            tool_choice={"type": "tool", "name": "record_resolutions"},
            messages=[{"role": "user", "content": prompt}],
        )

    def _enrich_with_claude(self, req: Requirement, conflicts: List[Conflict]) -> List[Conflict]:
        """Ask Claude for sharper resolution text; falls back to static text on any failure."""
        try:
            summary = self._summarize_requirements(req)
            conflict_lines = "\n".join(
                f"- type={c.type} severity={c.severity.value} fields={c.fields_involved} "
                f"description={c.description}"
                for c in conflicts
            )
            prompt = f"Requirements summary:\n{summary}\n\nDetected conflicts:\n{conflict_lines}"

            response = self._call_claude_raw(prompt)
            usage = getattr(response, "usage", None)
            api_cost_tracker.record_call(
                "claude",
                input_tokens=getattr(usage, "input_tokens", 0) if usage else 0,
                output_tokens=getattr(usage, "output_tokens", 0) if usage else 0,
            )

            tool_use = next((block for block in response.content if block.type == "tool_use"), None)
            if tool_use is None:
                return conflicts

            by_type = {
                item["type"]: item["suggested_resolution"]
                for item in tool_use.input.get("resolutions", [])
                if item.get("suggested_resolution")
            }
            for conflict in conflicts:
                if conflict.type in by_type:
                    conflict.suggested_resolution = by_type[conflict.type]
            return conflicts
        except Exception:
            logger.warning("Claude resolution enrichment failed; using static suggestions.", exc_info=True)
            return conflicts


_conflict_resolver: Optional[ConflictResolver] = None


def get_conflict_resolver() -> ConflictResolver:
    """Return a process-wide singleton ConflictResolver (FastAPI dependency)."""
    global _conflict_resolver
    if _conflict_resolver is None:
        _conflict_resolver = ConflictResolver()
    return _conflict_resolver

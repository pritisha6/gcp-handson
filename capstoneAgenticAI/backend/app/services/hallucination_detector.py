"""Detects design claims that cannot be traced back to a document, API response, or database record."""
import json
from typing import Any, Dict, List, Optional

from anthropic import Anthropic
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import Settings, get_settings
from app.schemas.design import Design, DesignOutput
from app.schemas.guardrail import Hallucination
from app.utils.api_cost_tracker import api_cost_tracker
from app.utils.errors import ExternalServiceError
from app.utils.logger import get_logger

logger = get_logger(__name__)

_SYSTEM_PROMPT = """You are a fact-checking auditor for an AI-generated GCP architecture design. You \
will be given:
1. "reasoning_text": free-form explanatory text written by the design agent.
2. "known_facts": structured data (cost figures, compliance results, selected services) that IS \
traceable to the design's own retrieved documents, API responses, and cost calculations.

Find every specific factual claim in reasoning_text that asserts a concrete number, price, rate, or \
capability (e.g. "$0.02 per million messages", "handles 100K msgs/sec", "meets SOC2 out of the box"). \
For each such claim, decide whether it is directly supported by known_facts.

- If the claim's specific figure/assertion appears in (or is clearly consistent with) known_facts, it \
is sourced - do not report it.
- If the claim asserts a specific number or capability that does NOT appear anywhere in known_facts, \
report it as a potential hallucination: the design has no traceable source for that specific figure.

General or qualitative statements without a specific verifiable figure (e.g. "Pub/Sub is a managed \
service") are not hallucinations even if unsourced.

Always respond by calling the record_hallucinations tool, with an empty list if nothing is flagged."""

_HALLUCINATION_TOOL = {
    "name": "record_hallucinations",
    "description": "Record any factual claims in reasoning_text that are not traceable to known_facts.",
    "input_schema": {
        "type": "object",
        "properties": {
            "hallucinations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "claim": {"type": "string"},
                        "reason": {"type": "string"},
                        "confidence": {"type": "number"},
                    },
                    "required": ["claim", "reason", "confidence"],
                },
            }
        },
        "required": ["hallucinations"],
    },
}


class HallucinationDetector:
    """Scans a Design's free-text reasoning for claims not traceable to its own structured data."""

    def __init__(self, client: Optional[Anthropic] = None, settings: Optional[Settings] = None) -> None:
        self._settings = settings or get_settings()
        self._client = client or Anthropic(api_key=self._settings.CLAUDE_API_KEY)

    def detect_hallucinations(self, design: Design) -> List[Hallucination]:
        """Find claims in a design's reasoning text with no traceable source.

        Args:
            design: The design to audit. Only ``design.output`` is inspected;
                designs with no output yet produce no findings.

        Returns:
            Unsourced claims found, if any. Never raises: a failed Claude
            call is logged and treated as "no findings" rather than blocking
            the rest of the validation pipeline.
        """
        if design.output is None:
            return []

        reasoning_text = self._collect_reasoning_text(design.output)
        if not reasoning_text.strip():
            return []

        known_facts = self._collect_known_facts(design.output)

        try:
            raw = self._call_claude(reasoning_text, known_facts)
        except Exception:
            logger.exception("Hallucination detection failed for design '%s'; skipping check", design.id)
            return []

        hallucinations = [
            Hallucination(
                claim=item["claim"],
                location="output.decision_matrix.reasoning",
                reason=item["reason"],
                confidence=item["confidence"],
            )
            for item in raw.get("hallucinations", [])
        ]
        if hallucinations:
            logger.warning(
                "Detected %d potential hallucination(s) in design '%s'", len(hallucinations), design.id
            )
        return hallucinations

    def confidence_penalty(self, hallucinations: List[Hallucination]) -> float:
        """Suggested reduction (0-1) to overall design confidence given detected hallucinations.

        Callers combine this with the design's own confidence score (e.g.
        the Tree-of-Thought ``final_score``) rather than this detector
        mutating the Design directly.
        """
        penalty = sum(0.1 + 0.1 * h.confidence for h in hallucinations)
        return min(penalty, 0.9)

    # --- Helpers ---

    def _collect_reasoning_text(self, output: DesignOutput) -> str:
        parts: List[str] = []
        if output.decision_matrix and output.decision_matrix.get("reasoning"):
            parts.append(str(output.decision_matrix["reasoning"]))
        if output.implementation_roadmap and output.implementation_roadmap.get("phases"):
            for phase in output.implementation_roadmap["phases"]:
                if isinstance(phase, dict) and phase.get("description"):
                    parts.append(str(phase["description"]))
        return "\n".join(parts)

    def _collect_known_facts(self, output: DesignOutput) -> Dict[str, Any]:
        decision_matrix = output.decision_matrix or {}
        return {
            "cost_analysis": output.cost_analysis or {},
            "compliance_checklist": output.compliance_checklist or {},
            "selected_path": decision_matrix.get("selected_path", []),
            "final_score": decision_matrix.get("final_score"),
            "alternatives": decision_matrix.get("alternatives", []),
        }

    @retry(reraise=True, stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=30))
    def _call_claude_raw(self, reasoning_text: str, known_facts: Dict[str, Any]):
        user_content = json.dumps({"reasoning_text": reasoning_text, "known_facts": known_facts}, default=str)
        return self._client.messages.create(
            model=self._settings.CLAUDE_MODEL,
            max_tokens=2048,
            temperature=0,
            system=_SYSTEM_PROMPT,
            tools=[_HALLUCINATION_TOOL],
            tool_choice={"type": "tool", "name": "record_hallucinations"},
            messages=[{"role": "user", "content": user_content}],
        )

    def _call_claude(self, reasoning_text: str, known_facts: Dict[str, Any]) -> Dict[str, Any]:
        try:
            response = self._call_claude_raw(reasoning_text, known_facts)
        except Exception as exc:
            raise ExternalServiceError("claude", f"hallucination detection failed: {exc}") from exc

        usage = getattr(response, "usage", None)
        api_cost_tracker.record_call(
            "claude",
            input_tokens=getattr(usage, "input_tokens", 0) if usage else 0,
            output_tokens=getattr(usage, "output_tokens", 0) if usage else 0,
        )

        tool_use = next((block for block in response.content if block.type == "tool_use"), None)
        if tool_use is None:
            raise ExternalServiceError("claude", "no structured hallucination report returned")
        return tool_use.input


_hallucination_detector: Optional[HallucinationDetector] = None


def get_hallucination_detector() -> HallucinationDetector:
    """Return a process-wide singleton HallucinationDetector (FastAPI dependency)."""
    global _hallucination_detector
    if _hallucination_detector is None:
        _hallucination_detector = HallucinationDetector()
    return _hallucination_detector

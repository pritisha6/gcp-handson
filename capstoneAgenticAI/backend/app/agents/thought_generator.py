"""Generates candidate services for one Tree-of-Thought architecture layer, via Groq."""
import hashlib
import json
from typing import Any, Dict, List, Optional

from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import Settings, get_settings
from app.schemas.tot import LAYERS, Candidate
from app.utils.api_cost_tracker import api_cost_tracker
from app.utils.cache import TTLCache
from app.utils.errors import ExternalServiceError
from app.utils.llm_client import ToolCallResult, call_tool, get_llm_client
from app.utils.logger import get_logger

logger = get_logger(__name__)

_CACHE_TTL_SECONDS = 60 * 60  # 1 hour: candidates rarely need to change within one design session

_SYSTEM_PROMPT = """You are a GCP architecture expert. Given ETL pipeline requirements and a target \
architecture layer, suggest 3-5 candidate services for that layer.

If earlier layers have already been selected (see 'selected_services' in the input), choose \
candidates that integrate well with those choices.

For each candidate service, provide:
- service: the service name (e.g. 'Pub/Sub', 'Kafka on GKE', 'Dataflow')
- rationale: why it fits this scenario
- estimated_cost: a rough estimated monthly cost in USD, as a number
- tradeoffs: a short list of known downsides or trade-offs
- feasibility: your confidence (0-1) that this service can technically satisfy the stated requirements

Always respond by calling the record_candidates tool."""

_CANDIDATES_TOOL = {
    "name": "record_candidates",
    "description": "Record 3-5 candidate services for the given architecture layer.",
    "input_schema": {
        "type": "object",
        "properties": {
            "candidates": {
                "type": "array",
                "minItems": 3,
                "maxItems": 5,
                "items": {
                    "type": "object",
                    "properties": {
                        "service": {"type": "string"},
                        "rationale": {"type": "string"},
                        "estimated_cost": {"type": "number"},
                        "tradeoffs": {"type": "array", "items": {"type": "string"}},
                        "feasibility": {"type": "number"},
                    },
                    "required": ["service", "rationale", "estimated_cost", "tradeoffs", "feasibility"],
                },
            }
        },
        "required": ["candidates"],
    },
}


class ThoughtGenerator:
    """Proposes candidate services for one ToT architecture layer using Groq.

    Determinism note: the model's own sampling is not perfectly reproducible
    even at ``temperature=0``, but that is the closest practical approximation
    to a fixed seed the chat completions API offers; all *our* logic
    downstream (caching, sorting, pruning) is fully deterministic given the
    same model output.
    """

    def __init__(
        self,
        client: Optional[OpenAI] = None,
        settings: Optional[Settings] = None,
        cache: Optional[TTLCache] = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._client = client or get_llm_client(self._settings)
        self._cache = cache or TTLCache()

    def generate_candidates(self, requirements: Dict[str, Any], layer: str) -> List[Candidate]:
        """Generate candidate services for one architecture layer.

        Args:
            requirements: Requirement data (typically ``Requirement.model_dump()``),
                optionally including a ``"selected_services"`` map of layer ->
                already-chosen service name for upstream layers.
            layer: One of "ingestion", "processing", "storage", "serving".

        Returns:
            3-5 candidate services, cached per (layer, requirements) for 1 hour.

        Raises:
            ValueError: If ``layer`` is not a recognized architecture layer.
            ExternalServiceError: If Groq cannot be reached or returns no candidates.
        """
        if layer not in LAYERS:
            raise ValueError(f"Unknown layer '{layer}'; expected one of {LAYERS}.")

        cache_key = self._cache_key(requirements, layer)
        cached = self._cache.get(cache_key)
        if cached is not None:
            logger.info("Thought generation cache hit for layer '%s'", layer)
            return cached

        raw = self._call_groq(requirements, layer)
        candidates = [Candidate.model_validate(c) for c in raw.get("candidates", [])]
        if not candidates:
            logger.warning("Groq returned no candidates for layer '%s'", layer)

        self._cache.set(cache_key, candidates, _CACHE_TTL_SECONDS)
        return candidates

    def _cache_key(self, requirements: Dict[str, Any], layer: str) -> str:
        payload = json.dumps({"layer": layer, "requirements": requirements}, sort_keys=True, default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @retry(reraise=True, stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=30))
    def _call_groq_raw(self, requirements: Dict[str, Any], layer: str) -> ToolCallResult:
        user_content = json.dumps({"layer": layer, "requirements": requirements}, default=str)
        return call_tool(
            self._client,
            model=self._settings.GROQ_MODEL,
            system_prompt=_SYSTEM_PROMPT,
            user_content=user_content,
            tool_name="record_candidates",
            tool_description=_CANDIDATES_TOOL["description"],
            input_schema=_CANDIDATES_TOOL["input_schema"],
            max_tokens=2048,
            temperature=0,
        )

    def _call_groq(self, requirements: Dict[str, Any], layer: str) -> Dict[str, Any]:
        try:
            result = self._call_groq_raw(requirements, layer)
        except Exception as exc:
            logger.exception("Groq call failed during thought generation for layer '%s'", layer)
            raise ExternalServiceError("groq", f"thought generation failed for layer '{layer}': {exc}") from exc

        api_cost_tracker.record_call(
            "groq",
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
        )

        return result.arguments


_thought_generator: Optional[ThoughtGenerator] = None


def get_thought_generator() -> ThoughtGenerator:
    """Return a process-wide singleton ThoughtGenerator (FastAPI dependency)."""
    global _thought_generator
    if _thought_generator is None:
        _thought_generator = ThoughtGenerator()
    return _thought_generator

"""Tracks token usage and estimated spend for external LLM/embedding API calls.

Used across services (RequirementExtractor, ConflictResolver, PineconeClient's
embedding calls) to log a running total of calls and estimated cost. This is
distinct from ``CostCalculator``, which estimates the cost of the *generated
GCP architecture*, not our own API usage.
"""
from dataclasses import dataclass
from threading import Lock
from typing import Dict

from app.utils.logger import get_logger

logger = get_logger(__name__)

# Approximate list pricing, USD per 1M units (tokens for LLMs, tokens for embeddings).
# Update as vendor pricing changes; these are estimates for cost-tracking purposes only.
_PRICING_PER_MILLION: Dict[str, Dict[str, float]] = {
    "groq": {"input": 0.59, "output": 0.79},  # llama-3.3-70b-versatile
    "local_embedding": {"input": 0.0, "output": 0.0},  # runs on-device, no per-call cost
}


@dataclass
class _UsageTotals:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


class ApiCostTracker:
    """Accumulates call counts, token usage, and estimated cost per provider."""

    def __init__(self) -> None:
        self._totals: Dict[str, _UsageTotals] = {}
        self._lock = Lock()

    def record_call(self, provider: str, input_tokens: int = 0, output_tokens: int = 0) -> float:
        """Record one API call and return its estimated cost in USD."""
        pricing = _PRICING_PER_MILLION.get(provider, {"input": 0.0, "output": 0.0})
        cost = (input_tokens / 1_000_000) * pricing["input"] + (output_tokens / 1_000_000) * pricing["output"]

        with self._lock:
            totals = self._totals.setdefault(provider, _UsageTotals())
            totals.calls += 1
            totals.input_tokens += input_tokens
            totals.output_tokens += output_tokens
            totals.cost_usd += cost

        logger.info(
            "API call recorded: provider=%s input_tokens=%d output_tokens=%d cost_usd=%.6f",
            provider,
            input_tokens,
            output_tokens,
            cost,
        )
        return cost

    def summary(self) -> Dict[str, Dict[str, float]]:
        """Return a snapshot of accumulated usage/cost per provider."""
        with self._lock:
            return {
                provider: {
                    "calls": totals.calls,
                    "input_tokens": totals.input_tokens,
                    "output_tokens": totals.output_tokens,
                    "cost_usd": round(totals.cost_usd, 6),
                }
                for provider, totals in self._totals.items()
            }


api_cost_tracker = ApiCostTracker()

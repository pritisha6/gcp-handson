"""Beam-search decision making over scored Tree-of-Thought candidates."""
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from app.agents.critic_evaluator import CriticEvaluator
from app.schemas.tot import Candidate, EvalResult
from app.utils.logger import get_logger

if TYPE_CHECKING:
    from app.services.guardrail_validator import GuardrailValidator

logger = get_logger(__name__)

# Criteria that force a candidate out regardless of its overall final_score.
_HARD_FAIL_CRITERIA = ("latency", "compliance")


class DecisionMaker:
    """Scores candidates via CriticEvaluator, prunes hard failures, and keeps the top-K beam.

    Optionally also runs each surviving candidate through a
    ``GuardrailValidator`` (SET 2: Service Selection) as an additional
    hard-gate pruning pass, so the safety guardrail system is genuinely
    wired into live service selection rather than only being callable
    standalone. Left unset by default (no behavior change) since
    constructing a full ``GuardrailValidator`` pulls in several heavier
    dependencies (Claude, Firestore) that not every caller needs.
    """

    def __init__(
        self,
        critic_evaluator: Optional[CriticEvaluator] = None,
        beam_width: int = 3,
        guardrail_validator: Optional["GuardrailValidator"] = None,
    ) -> None:
        self._critic_evaluator = critic_evaluator or CriticEvaluator()
        self._beam_width = beam_width
        self._guardrail_validator = guardrail_validator
        self._decision_trail: List[Dict[str, Any]] = []

    def make_decision(
        self, candidates: List[Dict[str, Any]], level: str, requirements: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Score, prune, and select from a list of candidates for one layer.

        Args:
            candidates: Raw candidate dicts (as produced by ``ThoughtGenerator``).
            level: The architecture layer these candidates belong to (for logging/audit).
            requirements: Requirement data to score candidates against.

        Returns:
            ``{"level", "selected", "beam", "pruned"}`` where ``selected`` is the
            single best surviving candidate (with its evaluation), ``beam`` is
            the top ``beam_width`` survivors (for continuing a multi-path
            search), and ``pruned`` lists every candidate removed and why.
        """
        evaluated: List[EvalResult] = []
        for raw in candidates:
            candidate = raw if isinstance(raw, Candidate) else Candidate.model_validate(raw)
            evaluated.append(self._critic_evaluator.evaluate(candidate.model_dump(), requirements))

        kept: List[EvalResult] = []
        pruned: List[Dict[str, Any]] = []
        for result in evaluated:
            failed_criteria = [c for c in _HARD_FAIL_CRITERIA if getattr(result.scores, c) == 0.0]
            if failed_criteria:
                pruned.append(
                    {
                        "candidate": result.candidate.service,
                        "reason": f"hard failure: {', '.join(failed_criteria)}",
                        "final_score": result.final_score,
                    }
                )
            else:
                kept.append(result)

        if self._guardrail_validator is not None:
            kept = self._apply_guardrails(kept, requirements, pruned)

        kept.sort(key=lambda r: r.final_score, reverse=True)
        beam = kept[: self._beam_width]
        for result in kept[self._beam_width :]:
            pruned.append(
                {"candidate": result.candidate.service, "reason": "beam_width exceeded", "final_score": result.final_score}
            )

        selected = beam[0] if beam else None

        trail_entry = {
            "timestamp": time.time(),
            "level": level,
            "candidates_considered": len(candidates),
            "kept": [r.candidate.service for r in beam],
            "pruned": pruned,
            "selected": selected.candidate.service if selected else None,
        }
        self._decision_trail.append(trail_entry)

        logger.info(
            "DecisionMaker[%s]: considered=%d kept=%d pruned=%d selected=%s",
            level,
            len(candidates),
            len(beam),
            len(pruned),
            trail_entry["selected"],
        )

        return {
            "level": level,
            "selected": selected.model_dump() if selected else None,
            "beam": [r.model_dump() for r in beam],
            "pruned": pruned,
        }

    def get_decision_trail(self) -> List[Dict[str, Any]]:
        """Return the full audit trail of every decision made by this instance."""
        return list(self._decision_trail)

    def _apply_guardrails(
        self, kept: List[EvalResult], requirements: Dict[str, Any], pruned: List[Dict[str, Any]]
    ) -> List[EvalResult]:
        """Hard-prune any candidate that fails a STOP-status guardrail check (SET 2)."""
        from app.schemas.design import Requirement  # local import: avoids a hard dependency for callers who never set this

        requirement_model = Requirement.model_validate(requirements)
        survivors: List[EvalResult] = []
        for result in kept:
            candidate_dict = {**result.candidate.model_dump(), "selected_services": requirements.get("selected_services")}
            guardrail_results = self._guardrail_validator.validate_service_candidate(candidate_dict, requirement_model)
            stop_results = [r for r in guardrail_results if r.status.value == "STOP"]
            if stop_results:
                pruned.append(
                    {
                        "candidate": result.candidate.service,
                        "reason": f"guardrail STOP: {stop_results[0].source} - {stop_results[0].message}",
                        "final_score": result.final_score,
                    }
                )
            else:
                survivors.append(result)
        return survivors

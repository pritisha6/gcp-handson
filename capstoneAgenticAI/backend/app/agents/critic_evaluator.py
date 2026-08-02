"""Scores Tree-of-Thought candidates against latency, cost, ops, and compliance criteria."""
from typing import Any, Dict, Optional, Tuple

from app.config import Settings, get_settings
from app.schemas.tot import Candidate, EvalResult, ScoreBreakdown
from app.services.rag_system import RAGSystem, get_rag_system
from app.utils.gcp_reference_data import (
    LATENCY_TIER_BY_SERVICE,
    LOOSE_FRESHNESS_VALUES,
    OPS_COMPLEXITY_BY_SERVICE,
    RELEVANT_SKILL_KEYWORDS,
    TIGHT_FRESHNESS_VALUES,
    tier_for_service,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

# final_score = 0.30*latency + 0.30*cost + 0.25*ops + 0.15*compliance
_WEIGHTS = {"latency": 0.30, "cost": 0.30, "ops": 0.25, "compliance": 0.15}


class CriticEvaluator:
    """Scores a single ToT candidate against latency, cost, ops, and compliance criteria."""

    def __init__(self, rag_system: Optional[RAGSystem] = None, settings: Optional[Settings] = None) -> None:
        self._settings = settings or get_settings()
        self._rag_system = rag_system or get_rag_system()

    def evaluate(self, candidate: Dict[str, Any], requirements: Dict[str, Any]) -> EvalResult:
        """Score one candidate against the four weighted criteria.

        Args:
            candidate: A candidate dict (or ``Candidate``) with at least
                ``service`` and ``estimated_cost``.
            requirements: Requirement data (typically ``Requirement.model_dump()``).

        Returns:
            An ``EvalResult`` with per-criterion scores, the weighted final
            score, human-readable reasoning, and a confidence level.
        """
        candidate_model = candidate if isinstance(candidate, Candidate) else Candidate.model_validate(candidate)

        latency_score, latency_note, latency_confident = self._score_latency(candidate_model, requirements)
        cost_score, cost_note, cost_confident = self._score_cost(candidate_model, requirements)
        ops_score, ops_note = self._score_ops(candidate_model, requirements)
        compliance_score, compliance_note, compliance_confident = self._score_compliance(
            candidate_model, requirements
        )

        scores = ScoreBreakdown(latency=latency_score, cost=cost_score, ops=ops_score, compliance=compliance_score)
        final_score = round(
            _WEIGHTS["latency"] * latency_score
            + _WEIGHTS["cost"] * cost_score
            + _WEIGHTS["ops"] * ops_score
            + _WEIGHTS["compliance"] * compliance_score,
            4,
        )

        confidence = 1.0
        if not latency_confident:
            confidence -= 0.15
        if not cost_confident:
            confidence -= 0.15
        if not compliance_confident:
            confidence -= 0.10
        confidence = max(0.0, min(1.0, confidence))

        reasoning = " ".join([latency_note, cost_note, ops_note, compliance_note])

        result = EvalResult(
            candidate=candidate_model,
            scores=scores,
            final_score=final_score,
            reasoning=reasoning,
            confidence=confidence,
        )
        logger.info(
            "Evaluated '%s': final=%.3f (latency=%.2f cost=%.2f ops=%.2f compliance=%.2f, confidence=%.2f)",
            candidate_model.service,
            final_score,
            latency_score,
            cost_score,
            ops_score,
            compliance_score,
            confidence,
        )
        return result

    # --- Helpers ---

    def _score_latency(self, candidate: Candidate, requirements: Dict[str, Any]) -> Tuple[float, str, bool]:
        performance = requirements.get("performance", {}) or {}
        sla_minutes = performance.get("latency_sla_minutes", 60) or 60
        freshness = str(performance.get("data_freshness", "")).lower()

        tier = tier_for_service(LATENCY_TIER_BY_SERVICE, candidate.service)
        confident = tier is not None
        source = "known service profile"
        if tier is None:
            try:
                docs = self._rag_system.retrieve_documents(f"{candidate.service} latency performance", top_k=3)
            except Exception:
                docs = []
            tier = "near-real-time"
            source = "inferred from indexed documents" if docs else "no reference data available; assumed"

        tight_sla = sla_minutes <= 15 or freshness in TIGHT_FRESHNESS_VALUES
        loose_sla = sla_minutes >= 120 or freshness in LOOSE_FRESHNESS_VALUES

        if tier == "streaming":
            score = 1.0
        elif tier == "near-real-time":
            score = 0.6 if tight_sla else 1.0
        else:  # batch
            score = 0.1 if tight_sla else (1.0 if loose_sla else 0.7)

        note = f"Latency: '{candidate.service}' is a {tier} service ({source}); SLA is {sla_minutes} min."
        return score, note, confident

    def _score_cost(self, candidate: Candidate, requirements: Dict[str, Any]) -> Tuple[float, str, bool]:
        budget = requirements.get("budget", {}) or {}
        monthly_cap = budget.get("monthly_cap_usd", 0) or 0

        if monthly_cap <= 0:
            return 0.5, "Cost: no budget cap provided; scored neutrally.", False

        ratio = candidate.estimated_cost / monthly_cap
        if ratio <= 0.5:
            score = 1.0
        elif ratio <= 0.8:
            score = 0.8
        elif ratio <= 1.0:
            score = 0.5
        elif ratio <= 1.5:
            score = 0.2
        else:
            score = 0.0

        note = f"Cost: ~${candidate.estimated_cost:,.0f}/mo is {ratio:.0%} of the ${monthly_cap:,.0f}/mo budget."
        return score, note, True

    def _score_ops(self, candidate: Candidate, requirements: Dict[str, Any]) -> Tuple[float, str]:
        team = requirements.get("team", {}) or {}
        team_size = team.get("size", 1) or 1
        skills = {str(s).strip().lower() for s in team.get("skills", [])}

        complexity = tier_for_service(OPS_COMPLEXITY_BY_SERVICE, candidate.service) or "medium"

        if complexity == "low":
            score = 1.0
        else:
            required_keywords = RELEVANT_SKILL_KEYWORDS.get(complexity, set())
            has_skill = any(any(kw in skill for kw in required_keywords) for skill in skills)
            if has_skill:
                score = 1.0 if team_size >= 2 else 0.7
            else:
                score = 0.3 if complexity == "medium" else 0.1

        note = f"Ops: '{candidate.service}' has {complexity} operational complexity for a team of {team_size}."
        return score, note

    def _score_compliance(self, candidate: Candidate, requirements: Dict[str, Any]) -> Tuple[float, str, bool]:
        compliance = requirements.get("compliance", {}) or {}
        regulations = compliance.get("regulations", []) or []
        encryption_enabled = compliance.get("encryption", True)

        if not regulations:
            return 1.0, "Compliance: no regulations specified.", True

        scores = []
        notes = []
        confident = True
        for regulation in regulations:
            try:
                rule = self._rag_system.get_compliance_rules(regulation)
            except Exception:
                rule = {}
            if not rule:
                confident = False
                scores.append(0.6)
                notes.append(f"no rule data found for {regulation}")
                continue
            satisfied = not (rule.get("requires_encryption") and not encryption_enabled)
            scores.append(1.0 if satisfied else 0.0)
            notes.append(f"{regulation}: {'satisfied' if satisfied else 'NOT satisfied (encryption required)'}")

        score = sum(scores) / len(scores)
        note = "Compliance: " + "; ".join(notes) + "."
        return score, note, confident


_critic_evaluator: Optional[CriticEvaluator] = None


def get_critic_evaluator() -> CriticEvaluator:
    """Return a process-wide singleton CriticEvaluator (FastAPI dependency)."""
    global _critic_evaluator
    if _critic_evaluator is None:
        _critic_evaluator = CriticEvaluator()
    return _critic_evaluator

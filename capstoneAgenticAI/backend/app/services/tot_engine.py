"""Tree-of-Thought beam search across GCP architecture layers.

Searches ingestion -> processing -> storage -> serving, keeping the top
``beam_width`` scored paths at each layer (via ``ThoughtGenerator`` +
``DecisionMaker``/``CriticEvaluator``), and returns the best complete
architecture path found.
"""
import time
import uuid
from typing import Any, Dict, List, Optional

from app.agents.critic_evaluator import CriticEvaluator
from app.agents.decision_maker import DecisionMaker
from app.agents.state_manager import StateManager, get_state_manager
from app.agents.thought_generator import ThoughtGenerator, get_thought_generator
from app.config import Settings, get_settings
from app.schemas.tot import LAYERS, ArchitectureSearchResult, TreeNodeState
from app.utils.logger import get_logger

logger = get_logger(__name__)


class TreeOfThoughtEngine:
    """Beam search across ingestion -> processing -> storage -> serving layers."""

    def __init__(
        self,
        thought_generator: Optional[ThoughtGenerator] = None,
        critic_evaluator: Optional[CriticEvaluator] = None,
        decision_maker: Optional[DecisionMaker] = None,
        state_manager: Optional[StateManager] = None,
        settings: Optional[Settings] = None,
        beam_width: int = 3,
        confidence_threshold: float = 0.85,
        time_budget_seconds: float = 120.0,
        seed: int = 42,
    ) -> None:
        """Configure the search.

        Args:
            thought_generator: Candidate generator; defaults to a shared singleton.
            critic_evaluator: Used only if ``decision_maker`` is not provided.
            decision_maker: Scoring/pruning orchestrator; defaults to a new
                ``DecisionMaker`` wrapping ``critic_evaluator``.
            state_manager: Firestore-backed search state persistence.
            settings: Application settings.
            beam_width: Number of paths kept alive at each layer (K).
            confidence_threshold: Cumulative score at which the search can
                stop early once a complete path is found.
            time_budget_seconds: Wall-clock budget for the whole search.
            seed: Reserved for deterministic tie-breaking in our own
                sorting/pruning logic. Claude's generation is not fully
                reproducible even at temperature=0; this only guarantees our
                downstream logic is.
        """
        self._settings = settings or get_settings()
        self._thought_generator = thought_generator or get_thought_generator()
        self._decision_maker = decision_maker or DecisionMaker(critic_evaluator=critic_evaluator, beam_width=beam_width)
        self._state_manager = state_manager or get_state_manager()
        self._beam_width = beam_width
        self._confidence_threshold = confidence_threshold
        self._time_budget_seconds = time_budget_seconds
        self._seed = seed

    def search(self, requirements: Dict[str, Any], design_id: Optional[str] = None) -> Dict[str, Any]:
        """Run beam search over the four architecture layers.

        Args:
            requirements: Requirement data (typically ``Requirement.model_dump()``).
            design_id: Optional existing design id, to namespace persisted state.

        Returns:
            A dict matching ``ArchitectureSearchResult``: ``design_id``,
            ``status`` ("completed" | "escalated" | "partial"),
            ``termination_reason``, ``architecture_path``, ``services``,
            ``final_score``, ``reasoning``, and ``alternatives``.
        """
        design_id = design_id or str(uuid.uuid4())
        self._state_manager.initialize_state(design_id, requirements)

        start_time = time.monotonic()
        root = TreeNodeState(id=f"{design_id}-root", design_id=design_id, level=0, path=[], cumulative_score=1.0)
        beam: List[TreeNodeState] = [root]

        for depth, layer in enumerate(LAYERS, start=1):
            if time.monotonic() - start_time > self._time_budget_seconds:
                logger.warning("ToT search for '%s' exceeded time budget at layer '%s'", design_id, layer)
                return self._finalize(design_id, beam, "time_budget_exceeded", "partial")

            next_beam: List[TreeNodeState] = []
            trail_entries: List[Dict[str, Any]] = []

            for parent in beam:
                path_requirements = self._augment_requirements(requirements, parent)
                try:
                    candidates = self._thought_generator.generate_candidates(path_requirements, layer)
                except Exception:
                    logger.exception("Thought generation failed for layer '%s' from path %s", layer, parent.path)
                    continue
                if not candidates:
                    continue

                decision = self._decision_maker.make_decision(
                    [c.model_dump() for c in candidates], layer, path_requirements
                )
                trail_entries.append(decision)

                for survivor in decision["beam"]:
                    node = TreeNodeState(
                        id=str(uuid.uuid4()),
                        design_id=design_id,
                        level=depth,
                        layer=layer,
                        candidate=survivor["candidate"],
                        eval_result=survivor,
                        parent_id=parent.id,
                        path=parent.path + [survivor["candidate"]["service"]],
                        cumulative_score=self._combined_score(parent.cumulative_score, survivor["final_score"], depth),
                    )
                    self._state_manager.save_node(design_id, node)
                    next_beam.append(node)

            if not next_beam:
                return self._escalate(design_id, layer, beam, trail_entries)

            next_beam.sort(key=lambda n: n.cumulative_score, reverse=True)
            beam = next_beam[: self._beam_width]
            self._state_manager.update_best_paths(design_id, beam)

        best = max(beam, key=lambda n: n.cumulative_score)
        if best.cumulative_score >= self._confidence_threshold:
            return self._finalize(design_id, beam, "confidence_threshold_met", "completed")
        return self._finalize(design_id, beam, "depth_limit_reached", "completed")

    # --- Helpers ---

    def _augment_requirements(self, requirements: Dict[str, Any], parent: TreeNodeState) -> Dict[str, Any]:
        selected_services = {LAYERS[i]: service for i, service in enumerate(parent.path) if i < len(LAYERS)}
        return {**requirements, "selected_services": selected_services}

    def _combined_score(self, parent_cumulative: float, layer_score: float, depth: int) -> float:
        """Running average of per-layer final_scores across the path so far."""
        if depth <= 1:
            return layer_score
        return ((parent_cumulative * (depth - 1)) + layer_score) / depth

    def _finalize(self, design_id: str, beam: List[TreeNodeState], termination_reason: str, status: str) -> Dict[str, Any]:
        if not beam:
            return self._escalate(design_id, "unknown", beam, [])

        best = max(beam, key=lambda n: n.cumulative_score)
        services = {LAYERS[i]: service for i, service in enumerate(best.path) if i < len(LAYERS)}
        alternatives = [{"path": n.path, "cumulative_score": n.cumulative_score} for n in beam if n.id != best.id]

        reasoning = (
            f"Selected path {' -> '.join(best.path)} with cumulative score {best.cumulative_score:.3f} "
            f"({termination_reason.replace('_', ' ')})."
        )

        result = ArchitectureSearchResult(
            design_id=design_id,
            status=status,
            termination_reason=termination_reason,
            architecture_path=best.path,
            services=services,
            final_score=best.cumulative_score,
            reasoning=reasoning,
            alternatives=alternatives,
        )
        logger.info("ToT search finished for design '%s': %s (%s)", design_id, status, termination_reason)
        return result.model_dump()

    def _escalate(
        self, design_id: str, failed_layer: str, last_good_beam: List[TreeNodeState], trail_entries: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        best = max(last_good_beam, key=lambda n: n.cumulative_score) if last_good_beam else None
        pruned_reasons = sorted({p["reason"] for entry in trail_entries for p in entry.get("pruned", [])})
        reasoning = f"No feasible candidates survived layer '{failed_layer}'."
        if pruned_reasons:
            reasoning += f" All options were pruned: {', '.join(pruned_reasons)}."

        result = ArchitectureSearchResult(
            design_id=design_id,
            status="escalated",
            termination_reason="all_branches_pruned",
            architecture_path=best.path if best else [],
            services={LAYERS[i]: s for i, s in enumerate(best.path)} if best else {},
            final_score=best.cumulative_score if best else 0.0,
            reasoning=reasoning,
            alternatives=[],
        )
        logger.warning("ToT search escalated for design '%s' at layer '%s'", design_id, failed_layer)
        return result.model_dump()


_tot_engine: Optional[TreeOfThoughtEngine] = None


def get_tot_engine() -> TreeOfThoughtEngine:
    """Return a process-wide singleton TreeOfThoughtEngine (FastAPI dependency)."""
    global _tot_engine
    if _tot_engine is None:
        _tot_engine = TreeOfThoughtEngine()
    return _tot_engine

"""Main ETL architect agent: a 16-cycle ReAct loop orchestrated with LangGraph.

Cycles are grouped into 7 graph nodes:
    1-3   Discovery            - confirm/re-extract requirements, gather RAG context
    4-6   Conflict Detection   - call ConflictResolver
    7-10  Service Selection    - Tree-of-Thought search (ThoughtGenerator + CriticEvaluator)
    11-12 Compliance           - map compliance rules to the selected architecture
    13-14 Cost Analysis        - estimate total cost, justify budget overages
    15    Validation           - interim guardrail checks (see module note below)
    16    Documentation        - assemble the final Design output

Example scenario::

    from app.schemas.design import Requirement, DataSource, Performance, Budget, Team, Compliance

    requirements = Requirement(
        data_sources=[DataSource(name="clickstream", type="Messaging", size_gb=500,
                                  throughput_records_sec=200_000)],
        performance=Performance(latency_sla_minutes=15, peak_throughput_msgs_sec=200_000,
                                 data_freshness="near-real-time", p95_latency_minutes=10),
        budget=Budget(monthly_cap_usd=5_000),
        team=Team(size=4, skills=["python", "dataflow", "kafka"]),
        compliance=Compliance(),
    )
    design = ArchitectAgent().design(requirements, project_name="Clickstream Analytics")
"""
import uuid
from typing import Any, Dict, Iterator, List, Optional, TypedDict

from langgraph.graph import END, StateGraph

from app.config import Settings, get_settings
from app.schemas.conflict import Conflict
from app.schemas.design import Design, DesignOutput, DesignStatus, Requirement
from app.schemas.guardrail import GuardrailResult, GuardrailStatus
from app.schemas.tot import ProgressEvent
from app.services.conflict_resolver import ConflictResolver, get_conflict_resolver
from app.services.cost_calculator import CostCalculator
from app.services.guardrail_validator import GuardrailValidator, get_guardrail_validator
from app.services.rag_system import RAGSystem, get_rag_system
from app.services.requirement_extractor import RequirementExtractor, get_requirement_extractor
from app.services.tot_engine import TreeOfThoughtEngine, get_tot_engine
from app.utils.errors import NoFeasibleArchitectureError
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Maps common candidate service names (lowercased substring match) to the
# service keys CostCalculator's estimators understand.
_SERVICE_COST_KEY_MAP = {
    "pub/sub": "pubsub",
    "pubsub": "pubsub",
    "dataflow": "dataflow",
    "bigquery": "bigquery_storage",
    "cloud storage": "cloud_storage",
    "cloud functions": "cloud_functions",
    "firestore": "firestore",
}

_CYCLE_LABELS = {
    "discovery": "Discovery (Cycles 1-3)",
    "conflict_detection": "Conflict Detection (Cycles 4-6)",
    "service_selection": "Service Selection (Cycles 7-10)",
    "compliance": "Compliance (Cycles 11-12)",
    "cost_analysis": "Cost Analysis (Cycles 13-14)",
    "validation": "Validation (Cycle 15)",
    "documentation": "Documentation (Cycle 16)",
}


class AgentState(TypedDict, total=False):
    """Shared state threaded through the LangGraph cycle graph."""

    design_id: str
    project_name: str
    requirements: Requirement
    documents: List[str]
    extraction_warnings: List[str]
    conflicts: List[Conflict]
    architecture_result: Dict[str, Any]
    compliance_mapping: Dict[str, Any]
    cost_breakdown: Dict[str, Any]
    validation_issues: List[str]
    guardrail_results: List[GuardrailResult]
    design: Design


class ArchitectAgent:
    """Generates an optimal GCP ETL architecture design via a 16-cycle ReAct loop."""

    def __init__(
        self,
        requirement_extractor: Optional[RequirementExtractor] = None,
        conflict_resolver: Optional[ConflictResolver] = None,
        tot_engine: Optional[TreeOfThoughtEngine] = None,
        rag_system: Optional[RAGSystem] = None,
        cost_calculator: Optional[CostCalculator] = None,
        guardrail_validator: Optional[GuardrailValidator] = None,
        settings: Optional[Settings] = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._requirement_extractor = requirement_extractor or get_requirement_extractor()
        self._conflict_resolver = conflict_resolver or get_conflict_resolver()
        self._tot_engine = tot_engine or get_tot_engine()
        self._rag_system = rag_system or get_rag_system()
        self._cost_calculator = cost_calculator or CostCalculator(rag_system=self._rag_system)
        self._guardrail_validator = guardrail_validator or get_guardrail_validator()
        self._graph = self._build_graph()

    def design(
        self,
        requirements: Requirement,
        documents: Optional[List[str]] = None,
        project_name: str = "Untitled Design",
    ) -> Design:
        """Run the full 16-cycle ReAct loop and return the completed Design.

        Args:
            requirements: The (already-structured) pipeline requirements.
            documents: Optional supplementary raw document text; if given,
                Discovery re-extracts and cross-checks against ``requirements``.
            project_name: Human-readable project name for the resulting Design.

        Returns:
            The completed Design.

        Raises:
            NoFeasibleArchitectureError: If the loop finishes without producing a Design.
        """
        final_event: Optional[ProgressEvent] = None
        for event in self.stream_design(requirements, documents=documents, project_name=project_name):
            final_event = event

        if final_event is None or final_event.design is None:
            raise NoFeasibleArchitectureError("Design generation did not produce a result.")
        return final_event.design

    def stream_design(
        self,
        requirements: Requirement,
        documents: Optional[List[str]] = None,
        project_name: str = "Untitled Design",
    ) -> Iterator[ProgressEvent]:
        """Run the ReAct loop, yielding a ProgressEvent after each cycle group.

        The final yielded event's ``design`` field holds the completed Design.

        Args:
            requirements: The (already-structured) pipeline requirements.
            documents: Optional supplementary raw document text.
            project_name: Human-readable project name for the resulting Design.

        Yields:
            One ``ProgressEvent`` per completed cycle group, in order.
        """
        initial_state: AgentState = {
            "design_id": str(uuid.uuid4()),
            "project_name": project_name,
            "requirements": requirements,
            "documents": documents or [],
            "extraction_warnings": [],
            "conflicts": [],
            "architecture_result": {},
            "compliance_mapping": {},
            "cost_breakdown": {},
            "validation_issues": [],
            "guardrail_results": [],
        }

        for chunk in self._graph.stream(initial_state):
            for node_name, node_state in chunk.items():
                yield self._to_progress_event(node_name, node_state)

    # --- Graph construction ---

    def _build_graph(self):
        graph = StateGraph(AgentState)
        graph.add_node("discovery", self._node_discovery)
        graph.add_node("conflict_detection", self._node_conflict_detection)
        graph.add_node("service_selection", self._node_service_selection)
        graph.add_node("compliance", self._node_compliance)
        graph.add_node("cost_analysis", self._node_cost_analysis)
        graph.add_node("validation", self._node_validation)
        graph.add_node("documentation", self._node_documentation)

        graph.set_entry_point("discovery")
        graph.add_edge("discovery", "conflict_detection")
        graph.add_edge("conflict_detection", "service_selection")
        graph.add_edge("service_selection", "compliance")
        graph.add_edge("compliance", "cost_analysis")
        graph.add_edge("cost_analysis", "validation")
        graph.add_edge("validation", "documentation")
        graph.add_edge("documentation", END)
        return graph.compile()

    # --- Cycle nodes ---

    def _node_discovery(self, state: AgentState) -> Dict[str, Any]:
        """Cycles 1-3 (DISCOVERY): confirm requirements, optionally re-extract from documents."""
        requirements = state["requirements"]
        warnings: List[str] = []

        if state.get("documents"):
            try:
                extracted, extraction_warnings = self._requirement_extractor.extract_requirements_with_warnings(
                    state["documents"]
                )
                requirements = extracted
                warnings = extraction_warnings
                logger.info(
                    "Discovery: re-extracted requirements from %d supplementary document(s)",
                    len(state["documents"]),
                )
            except Exception:
                logger.exception("Discovery: requirement extraction from documents failed; using given requirements")

        logger.info("Discovery complete for design '%s'", state["design_id"])
        return {"requirements": requirements, "extraction_warnings": warnings}

    def _node_conflict_detection(self, state: AgentState) -> Dict[str, Any]:
        """Cycles 4-6 (CONFLICT DETECTION): call ConflictResolver.

        Conflicts are surfaced to downstream cycles (and the final design
        output) rather than silently auto-mutating the user's stated
        requirements; changing what the user asked for should be their call.
        """
        conflicts = self._conflict_resolver.detect_conflicts(state["requirements"])
        if conflicts:
            logger.warning(
                "Conflict detection found %d conflict(s) for design '%s': %s",
                len(conflicts),
                state["design_id"],
                [c.type for c in conflicts],
            )
        return {"conflicts": conflicts}

    def _node_service_selection(self, state: AgentState) -> Dict[str, Any]:
        """Cycles 7-10 (SERVICE SELECTION): run the Tree-of-Thought engine."""
        requirements_dict = state["requirements"].model_dump(mode="json")
        if state["conflicts"]:
            requirements_dict["known_conflicts"] = [c.model_dump(mode="json") for c in state["conflicts"]]

        result = self._tot_engine.search(requirements_dict, design_id=state["design_id"])
        logger.info(
            "Service selection for design '%s': status=%s path=%s",
            state["design_id"],
            result["status"],
            result.get("architecture_path"),
        )
        return {"architecture_result": result}

    def _node_compliance(self, state: AgentState) -> Dict[str, Any]:
        """Cycles 11-12 (COMPLIANCE): map compliance rules to the selected architecture."""
        requirements = state["requirements"]
        mapping: Dict[str, Any] = {}
        for regulation in requirements.compliance.regulations:
            try:
                rule = self._rag_system.get_compliance_rules(regulation)
            except Exception:
                logger.exception("Compliance lookup failed for '%s'", regulation)
                rule = {}
            satisfied = not (rule.get("requires_encryption") and not requirements.compliance.encryption)
            mapping[regulation] = {"rule": rule, "satisfied": satisfied}
        return {"compliance_mapping": mapping}

    def _node_cost_analysis(self, state: AgentState) -> Dict[str, Any]:
        """Cycles 13-14 (COST ANALYSIS): estimate total cost and justify overages.

        Kept Groq-free by design to control API spend on a cycle that runs
        on every design; the justification is a deterministic template.
        """
        requirements = state["requirements"]
        architecture = self._build_cost_architecture(state["architecture_result"], requirements)
        breakdown = self._cost_calculator.estimate_total_cost(architecture)

        cap = requirements.budget.monthly_cap_usd
        if cap and breakdown["total_usd"] > cap:
            overage = breakdown["total_usd"] - cap
            breakdown["budget_justification"] = (
                f"Estimated cost (${breakdown['total_usd']:,.0f}/mo) exceeds the ${cap:,.0f}/mo cap by "
                f"${overage:,.0f}. This reflects the throughput/latency requirements driving the selected "
                f"architecture; consider relaxing the latency SLA, reducing throughput, or increasing budget."
            )
        return {"cost_breakdown": breakdown}

    def _node_validation(self, state: AgentState) -> Dict[str, Any]:
        """Cycle 15 (VALIDATION): run the real GuardrailValidator (SET 3 + SET 4).

        Builds a preliminary Design from the state accumulated so far (every
        upstream cycle has already run) purely so ``validate_design``/
        ``validate_behavior`` have a real ``Design`` to inspect, per their
        literal signatures. Cycle 16 rebuilds the same Design and attaches
        these results to ``Design.validation_results``.
        """
        preliminary_design = self._assemble_design(state, validation_results=[])

        guardrail_results = list(self._guardrail_validator.validate_design(preliminary_design))
        guardrail_results.extend(self._guardrail_validator.validate_behavior(preliminary_design))

        blocking = [r for r in guardrail_results if r.status in (GuardrailStatus.STOP, GuardrailStatus.ESCALATE)]
        issues = [f"[{r.status.value}] {r.source}: {r.message}" for r in blocking]

        if issues:
            logger.warning("Validation found %d blocking guardrail result(s) for design '%s'", len(issues), state["design_id"])
        return {"validation_issues": issues, "guardrail_results": guardrail_results}

    def _node_documentation(self, state: AgentState) -> Dict[str, Any]:
        """Cycle 16 (DOCUMENTATION): assemble the final Design, with validation_results attached."""
        design = self._assemble_design(state, validation_results=state["guardrail_results"])
        logger.info("Documentation complete for design '%s' (status=%s)", state["design_id"], design.status.value)
        return {"design": design}

    # --- Helpers ---

    def _assemble_design(self, state: AgentState, validation_results: List[GuardrailResult]) -> Design:
        """Build a Design from the current accumulated state.

        Shared by Cycle 15 (to validate a real Design before it's "official")
        and Cycle 16 (to produce the final Design with validation_results attached).
        """
        architecture_result = state["architecture_result"]
        services = architecture_result.get("services", {})
        path = architecture_result.get("architecture_path", [])

        architecture_diagram = None
        if len(path) > 1:
            diagram_lines = ["flowchart LR"] + [f'    "{path[i]}" --> "{path[i + 1]}"' for i in range(len(path) - 1)]
            architecture_diagram = "\n".join(diagram_lines)

        decision_matrix = {
            "selected_path": path,
            "final_score": architecture_result.get("final_score"),
            "alternatives": architecture_result.get("alternatives", []),
            "reasoning": architecture_result.get("reasoning"),
            "conflicts": [c.model_dump(mode="json") for c in state["conflicts"]],
            "validation_issues": state.get("validation_issues", []),
        }

        roadmap = {
            "phases": [
                {"phase": 1, "name": "Ingestion setup", "service": services.get("ingestion")},
                {"phase": 2, "name": "Processing pipeline", "service": services.get("processing")},
                {"phase": 3, "name": "Storage & modeling", "service": services.get("storage")},
                {"phase": 4, "name": "Serving layer", "service": services.get("serving")},
            ]
        }

        output = DesignOutput(
            architecture_diagram=architecture_diagram,
            decision_matrix=decision_matrix,
            cost_analysis=state["cost_breakdown"],
            compliance_checklist=state["compliance_mapping"],
            implementation_roadmap=roadmap,
        )

        has_stop = any(r.status == GuardrailStatus.STOP for r in validation_results)
        status = (
            DesignStatus.FAILED if architecture_result.get("status") == "escalated" or has_stop else DesignStatus.COMPLETED
        )

        return Design(
            id=state["design_id"],
            project_name=state["project_name"],
            requirements=state["requirements"],
            status=status,
            output=output,
            validation_results=validation_results,
        )

    def _build_cost_architecture(self, architecture_result: Dict[str, Any], requirements: Requirement) -> Dict[str, Any]:
        services = architecture_result.get("services", {})
        total_size_gb = sum(ds.size_gb for ds in requirements.data_sources)

        architecture: Dict[str, Any] = {}
        if "ingestion" in services:
            architecture["ingestion"] = {
                "service": self._cost_service_key(services["ingestion"]),
                "requirements": {
                    "throughput_msgs_sec": requirements.performance.peak_throughput_msgs_sec,
                    "avg_message_size_kb": 1.0,
                },
            }
        if "processing" in services:
            architecture["processing"] = {
                "service": self._cost_service_key(services["processing"]),
                "requirements": {"worker_count": 2, "vcpus_per_worker": 2, "hours_per_month": 730},
            }
        if "storage" in services:
            architecture["storage"] = {
                "service": self._cost_service_key(services["storage"]),
                "requirements": {"size_gb": total_size_gb},
            }
        return architecture

    def _cost_service_key(self, service_name: str) -> str:
        name = service_name.lower()
        for keyword, key in _SERVICE_COST_KEY_MAP.items():
            if keyword in name:
                return key
        return "cloud_storage"  # conservative default for services outside the known cost model

    def _to_progress_event(self, node_name: str, node_state: Dict[str, Any]) -> ProgressEvent:
        label = _CYCLE_LABELS.get(node_name, node_name)
        return ProgressEvent(
            cycle=label,
            message=f"Completed {label}",
            data={k: v for k, v in node_state.items() if k != "design"},
            design=node_state.get("design"),
        )


_architect_agent: Optional[ArchitectAgent] = None


def get_architect_agent() -> ArchitectAgent:
    """Return a process-wide singleton ArchitectAgent (FastAPI dependency)."""
    global _architect_agent
    if _architect_agent is None:
        _architect_agent = ArchitectAgent()
    return _architect_agent

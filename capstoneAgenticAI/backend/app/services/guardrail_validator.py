"""Safety guardrail validation across all four design stages.

Status/severity mapping from this system's informal per-guardrail action
vocabulary onto ``GuardrailResult``'s canonical ``status``/``severity``
fields:

    PRUNE                          -> status=STOP,     severity=ERROR
    WARN     (<=10% over budget)   -> status=FLAG,      severity=WARN
    CAUTION  (10-50% over budget)  -> status=ESCALATE,  severity=WARN
    ERROR    (>50% over budget)    -> status=ESCALATE,  severity=ERROR
    FLAG     (missing controls/skills) -> status=FLAG,  severity=WARN or ERROR
"""
import json
import math
from typing import Any, Callable, Dict, List, Optional

from app.schemas.conflict import ConflictSeverity
from app.schemas.design import Design, Requirement
from app.schemas.guardrail import GuardrailResult, GuardrailSeverity, GuardrailStatus
from app.services.compliance_validator import ComplianceValidator, get_compliance_validator
from app.services.conflict_resolver import ConflictResolver, get_conflict_resolver
from app.services.cost_validator import CostValidator, get_cost_validator
from app.services.hallucination_detector import HallucinationDetector, get_hallucination_detector
from app.utils.gcp_reference_data import (
    GCP_LIMITS,
    INCOMPATIBLE_PAIRS,
    OPS_COMPLEXITY_BY_SERVICE,
    RELEVANT_SKILL_KEYWORDS,
    LATENCY_TIER_BY_SERVICE,
    TIGHT_FRESHNESS_VALUES,
    TRAINING_ESTIMATE_BY_COMPLEXITY,
    tier_for_service,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

_STATUS_RANK = {GuardrailStatus.STOP: 0, GuardrailStatus.ESCALATE: 1, GuardrailStatus.FLAG: 2, GuardrailStatus.PASS: 3}
_DR_KEYWORDS = ("disaster recovery", " dr ", "backup", "failover", "multi-region", "multi region")


class GuardrailValidator:
    """Runs safety guardrail checks across input, service-selection, design, and behavioral stages."""

    def __init__(
        self,
        conflict_resolver: Optional[ConflictResolver] = None,
        compliance_validator: Optional[ComplianceValidator] = None,
        cost_validator: Optional[CostValidator] = None,
        hallucination_detector: Optional[HallucinationDetector] = None,
    ) -> None:
        self._conflict_resolver = conflict_resolver or get_conflict_resolver()
        self._compliance_validator = compliance_validator or get_compliance_validator()
        self._cost_validator = cost_validator or get_cost_validator()
        self._hallucination_detector = hallucination_detector or get_hallucination_detector()

    # === SET 1: Input Validation ===

    def validate_requirements(self, requirements: Requirement) -> List[GuardrailResult]:
        """Run GR 1.1-1.3 against a submitted Requirement.

        Args:
            requirements: The requirement to validate.

        Returns:
            One or more GuardrailResults (completeness, contradictions, realism).
        """
        results: List[GuardrailResult] = [self._gr_1_1_completeness(requirements)]
        results.extend(self._gr_1_2_contradictions(requirements))
        results.extend(self._gr_1_3_realistic_constraints(requirements))
        self._log_results("validate_requirements", results)
        return results

    def _gr_1_1_completeness(self, requirements: Requirement) -> GuardrailResult:
        missing = []
        if not requirements.data_sources:
            missing.append("data_sources")
        if requirements.performance.latency_sla_minutes <= 0 and requirements.performance.p95_latency_minutes <= 0:
            missing.append("performance (latency SLA and p95 are both unset)")
        if requirements.budget.monthly_cap_usd <= 0:
            missing.append("budget.monthly_cap_usd")
        if requirements.team.size <= 0:
            missing.append("team.size")

        if missing:
            return GuardrailResult(
                status=GuardrailStatus.STOP,
                severity=GuardrailSeverity.ERROR,
                message=f"Requirements are incomplete: {', '.join(missing)}.",
                field=", ".join(missing),
                remediation="Provide values for the missing field(s) before generating a design.",
                source="GR 1.1 Requirements Complete",
            )
        return GuardrailResult(
            status=GuardrailStatus.PASS,
            severity=GuardrailSeverity.INFO,
            message="All required requirement fields are present.",
            field=None,
            remediation=None,
            source="GR 1.1 Requirements Complete",
        )

    def _gr_1_2_contradictions(self, requirements: Requirement) -> List[GuardrailResult]:
        conflicts = self._conflict_resolver.detect_conflicts(requirements)
        if not conflicts:
            return [
                GuardrailResult(
                    status=GuardrailStatus.PASS,
                    severity=GuardrailSeverity.INFO,
                    message="No contradictions detected among stated requirements.",
                    field=None,
                    remediation=None,
                    source="GR 1.2 Requirement Contradictions",
                )
            ]

        results = []
        for conflict in conflicts:
            is_error = conflict.severity == ConflictSeverity.ERROR
            results.append(
                GuardrailResult(
                    status=GuardrailStatus.STOP if is_error else GuardrailStatus.FLAG,
                    severity=GuardrailSeverity.ERROR if is_error else GuardrailSeverity.WARN,
                    message=conflict.description,
                    field=", ".join(conflict.fields_involved),
                    remediation=conflict.suggested_resolution,
                    source=f"GR 1.2 Contradiction ({conflict.type})",
                )
            )
        return results

    def _gr_1_3_realistic_constraints(self, requirements: Requirement) -> List[GuardrailResult]:
        throughput = requirements.performance.peak_throughput_msgs_sec
        per_partition_limit = GCP_LIMITS["pubsub_max_msgs_sec_per_partition"]
        practical_limit = GCP_LIMITS["pubsub_max_practical_msgs_sec_single_topic"]

        if throughput > practical_limit:
            return [
                GuardrailResult(
                    status=GuardrailStatus.STOP,
                    severity=GuardrailSeverity.ERROR,
                    message=(
                        f"Peak throughput of {throughput:,.0f} msgs/sec exceeds practical single-pipeline "
                        f"scale (~{practical_limit:,.0f} msgs/sec); confirm this figure or redesign for "
                        f"multi-pipeline ingestion."
                    ),
                    field="performance.peak_throughput_msgs_sec",
                    remediation="Confirm this figure, or split ingestion across multiple independent pipelines.",
                    source="GR 1.3 Realistic Constraints (throughput)",
                )
            ]
        if throughput > per_partition_limit:
            partitions_needed = math.ceil(throughput / per_partition_limit)
            return [
                GuardrailResult(
                    status=GuardrailStatus.FLAG,
                    severity=GuardrailSeverity.WARN,
                    message=(
                        f"Peak throughput of {throughput:,.0f} msgs/sec exceeds the ~{per_partition_limit:,.0f} "
                        f"msgs/sec guidance for a single Pub/Sub partition."
                    ),
                    field="performance.peak_throughput_msgs_sec",
                    remediation=f"Plan for at least {partitions_needed} partitions/topics to reach this throughput.",
                    source="GR 1.3 Realistic Constraints (throughput)",
                )
            ]
        return [
            GuardrailResult(
                status=GuardrailStatus.PASS,
                severity=GuardrailSeverity.INFO,
                message=f"Peak throughput of {throughput:,.0f} msgs/sec is within realistic single-pipeline limits.",
                field="performance.peak_throughput_msgs_sec",
                remediation=None,
                source="GR 1.3 Realistic Constraints (throughput)",
            )
        ]

    # === SET 2: Service Selection ===

    def validate_service_candidate(self, candidate: Dict[str, Any], requirements: Requirement) -> List[GuardrailResult]:
        """Run GR 2.1-2.5 against one candidate service for one architecture layer.

        Args:
            candidate: A candidate dict with at least ``service`` and
                ``estimated_cost``; may optionally include
                ``selected_services``/``upstream_services`` (layer -> service
                name already chosen) for the compatibility check.
            requirements: The requirements this candidate is being scored against.

        Returns:
            One GuardrailResult per GR 2.x check (compliance may contribute
            more than one, one per regulation).
        """
        results = [
            self._gr_2_1_latency(candidate, requirements),
            self._gr_2_2_cost(candidate, requirements),
            *self._gr_2_3_compliance(candidate, requirements),
            self._gr_2_4_compatibility(candidate, requirements),
            self._gr_2_5_team_skills(candidate, requirements),
        ]
        self._log_results("validate_service_candidate", results)
        return results

    def _gr_2_1_latency(self, candidate: Dict[str, Any], requirements: Requirement) -> GuardrailResult:
        service = candidate.get("service", "unknown")
        tier = tier_for_service(LATENCY_TIER_BY_SERVICE, service)
        sla = requirements.performance.latency_sla_minutes
        freshness = requirements.performance.data_freshness.lower()
        tight_sla = sla <= 15 or freshness in TIGHT_FRESHNESS_VALUES

        if tier == "batch" and tight_sla:
            return GuardrailResult(
                status=GuardrailStatus.STOP,
                severity=GuardrailSeverity.ERROR,
                message=f"'{service}' is a batch-oriented service and cannot meet the {sla}-minute latency SLA.",
                field="performance.latency_sla_minutes",
                remediation="Choose a streaming-capable service, or relax the latency SLA.",
                source="GR 2.1 Latency Feasibility (PRUNE)",
            )
        return GuardrailResult(
            status=GuardrailStatus.PASS,
            severity=GuardrailSeverity.INFO,
            message=f"'{service}' can plausibly meet the {sla}-minute latency SLA.",
            field="performance.latency_sla_minutes",
            remediation=None,
            source="GR 2.1 Latency Feasibility",
        )

    def _gr_2_2_cost(self, candidate: Dict[str, Any], requirements: Requirement) -> GuardrailResult:
        return self._cost_validator.validate_cost(
            candidate.get("estimated_cost", 0.0), requirements.budget.monthly_cap_usd
        )

    def _gr_2_3_compliance(self, candidate: Dict[str, Any], requirements: Requirement) -> List[GuardrailResult]:
        if not requirements.compliance.regulations:
            return [
                GuardrailResult(
                    status=GuardrailStatus.PASS,
                    severity=GuardrailSeverity.INFO,
                    message="No regulations specified; compliance check skipped.",
                    field=None,
                    remediation=None,
                    source="GR 2.3 Compliance Check",
                )
            ]
        architecture = {
            "encryption": requirements.compliance.encryption,
            "data_residency": requirements.compliance.data_residency,
        }
        return self._compliance_validator.check_compliance(architecture, requirements.compliance.regulations)

    def _gr_2_4_compatibility(self, candidate: Dict[str, Any], requirements: Requirement) -> GuardrailResult:
        service = str(candidate.get("service", "")).lower()
        upstream = candidate.get("selected_services") or candidate.get("upstream_services") or {}
        upstream_names = {str(v).lower() for v in upstream.values()} if isinstance(upstream, dict) else set()

        for pair in INCOMPATIBLE_PAIRS:
            pair_lower = {p.lower() for p in pair}
            matched_self = [p for p in pair_lower if p in service]
            if not matched_self:
                continue
            other_terms = pair_lower - set(matched_self)
            if any(any(term in upstream_name for term in other_terms) for upstream_name in upstream_names):
                return GuardrailResult(
                    status=GuardrailStatus.STOP,
                    severity=GuardrailSeverity.ERROR,
                    message=f"'{candidate.get('service')}' is not compatible with the already-selected {upstream}.",
                    field="architecture.services",
                    remediation="Choose a different service for this layer.",
                    source="GR 2.4 Service Compatibility (PRUNE)",
                )
        return GuardrailResult(
            status=GuardrailStatus.PASS,
            severity=GuardrailSeverity.INFO,
            message=f"No known incompatibilities between '{candidate.get('service')}' and the selected services.",
            field=None,
            remediation=None,
            source="GR 2.4 Service Compatibility",
        )

    def _gr_2_5_team_skills(self, candidate: Dict[str, Any], requirements: Requirement) -> GuardrailResult:
        service = str(candidate.get("service", ""))
        complexity = tier_for_service(OPS_COMPLEXITY_BY_SERVICE, service) or "medium"
        skills = {s.strip().lower() for s in requirements.team.skills}

        if complexity == "low":
            return GuardrailResult(
                status=GuardrailStatus.PASS,
                severity=GuardrailSeverity.INFO,
                message=f"'{service}' is low-complexity to operate; no specific skill gap expected.",
                field=None,
                remediation=None,
                source="GR 2.5 Team Skills Match",
            )

        required_keywords = RELEVANT_SKILL_KEYWORDS.get(complexity, set())
        has_skill = any(any(kw in skill for kw in required_keywords) for skill in skills)
        if has_skill:
            return GuardrailResult(
                status=GuardrailStatus.PASS,
                severity=GuardrailSeverity.INFO,
                message=f"Team has relevant skills for operating '{service}'.",
                field=None,
                remediation=None,
                source="GR 2.5 Team Skills Match",
            )

        training_estimate = TRAINING_ESTIMATE_BY_COMPLEXITY.get(complexity, "unknown training investment")
        return GuardrailResult(
            status=GuardrailStatus.FLAG,
            severity=GuardrailSeverity.WARN,
            message=f"Team's listed skills do not cover operating '{service}' ({complexity} complexity).",
            field="team.skills",
            remediation=f"Close the skill gap: {training_estimate}.",
            source="GR 2.5 Team Skills Gap",
        )

    # === SET 3: Design Validation ===

    def validate_design(self, design: Design) -> List[GuardrailResult]:
        """Run GR 3.1-3.5 against a (possibly still-being-assembled) Design.

        Args:
            design: The design to validate. ``design.output`` may be
                partially populated (this is also used mid-pipeline, before
                documentation finalizes the design).

        Returns:
            One GuardrailResult per GR 3.x check (compliance may contribute
            more than one).
        """
        results = [
            self._gr_3_1_coverage(design),
            self._gr_3_2_cost_justified(design),
            *self._gr_3_3_compliance_complete(design),
            self._gr_3_4_quotas(design),
            self._gr_3_5_dr_plan(design),
        ]
        self._log_results("validate_design", results)
        return results

    def _gr_3_1_coverage(self, design: Design) -> GuardrailResult:
        output = design.output
        dimensions = {
            "data_sources_considered": bool(design.requirements.data_sources),
            "architecture_diagram": bool(output and output.architecture_diagram),
            "cost_analysis": bool(output and output.cost_analysis),
            "compliance_checklist": bool(output)
            and (not design.requirements.compliance.regulations or bool(output.compliance_checklist)),
            "implementation_roadmap": bool(output and output.implementation_roadmap),
            "all_layers_selected": bool(
                output and output.decision_matrix and len(output.decision_matrix.get("selected_path", [])) >= 4
            ),
        }
        covered = sum(1 for v in dimensions.values() if v)
        coverage_ratio = covered / len(dimensions)
        missing = [k for k, v in dimensions.items() if not v]

        status = GuardrailStatus.PASS if coverage_ratio >= 0.9 else GuardrailStatus.FLAG
        severity = GuardrailSeverity.INFO if coverage_ratio >= 0.9 else GuardrailSeverity.WARN
        return GuardrailResult(
            status=status,
            severity=severity,
            message=f"Requirement coverage is {coverage_ratio:.0%} ({covered}/{len(dimensions)} dimensions).",
            field=", ".join(missing) if missing else None,
            remediation=f"Address: {', '.join(missing)}." if missing else None,
            source="GR 3.1 Requirement Coverage",
        )

    def _gr_3_2_cost_justified(self, design: Design) -> GuardrailResult:
        total = (design.output.cost_analysis or {}).get("total_usd", 0.0) if design.output else 0.0
        result = self._cost_validator.validate_cost(total, design.requirements.budget.monthly_cap_usd)
        return result.model_copy(update={"source": result.source.replace("GR 2.2", "GR 3.2")})

    def _gr_3_3_compliance_complete(self, design: Design) -> List[GuardrailResult]:
        regulations = design.requirements.compliance.regulations
        if not regulations:
            return [
                GuardrailResult(
                    status=GuardrailStatus.PASS,
                    severity=GuardrailSeverity.INFO,
                    message="No regulations specified; nothing to validate.",
                    field=None,
                    remediation=None,
                    source="GR 3.3 Compliance Complete",
                )
            ]
        architecture = {
            "encryption": design.requirements.compliance.encryption,
            "data_residency": design.requirements.compliance.data_residency,
        }
        results = self._compliance_validator.check_compliance(architecture, regulations)

        relabeled = []
        for result in results:
            # A gap surviving all the way to the final design is escalated, not just flagged.
            new_status = (
                GuardrailStatus.ESCALATE
                if result.status == GuardrailStatus.FLAG and result.severity == GuardrailSeverity.ERROR
                else result.status
            )
            relabeled.append(
                result.model_copy(update={"status": new_status, "source": result.source.replace("GR 2.3", "GR 3.3")})
            )
        return relabeled

    def _gr_3_4_quotas(self, design: Design) -> GuardrailResult:
        candidates = self._gr_1_3_realistic_constraints(design.requirements)
        worst = min(candidates, key=lambda r: _STATUS_RANK[r.status])
        return worst.model_copy(update={"source": worst.source.replace("GR 1.3", "GR 3.4")})

    def _gr_3_5_dr_plan(self, design: Design) -> GuardrailResult:
        output = design.output
        text = (
            json.dumps(
                {"roadmap": output.implementation_roadmap or {}, "compliance": output.compliance_checklist or {}},
                default=str,
            ).lower()
            if output
            else ""
        )

        if any(keyword in text for keyword in _DR_KEYWORDS):
            return GuardrailResult(
                status=GuardrailStatus.PASS,
                severity=GuardrailSeverity.INFO,
                message="A disaster recovery / backup plan reference was found in the design.",
                field=None,
                remediation=None,
                source="GR 3.5 DR Plan Included",
            )
        return GuardrailResult(
            status=GuardrailStatus.FLAG,
            severity=GuardrailSeverity.WARN,
            message="No disaster recovery / backup / failover plan was found in the design output.",
            field="output.implementation_roadmap",
            remediation="Add a disaster recovery plan (backup cadence, failover region, RTO/RPO targets).",
            source="GR 3.5 DR Plan Included",
        )

    # === SET 4: Behavioral ===

    def validate_behavior(self, design: Design) -> List[GuardrailResult]:
        """Run GR 4.1-4.4 against a Design's own explanations and confidence.

        Args:
            design: The design to audit.

        Returns:
            One GuardrailResult per GR 4.x check (hallucination detection may
            contribute more than one). GR 4.4 (determinism) cannot be
            assessed from a single Design; see ``check_determinism``.
        """
        hallucination_results = self._gr_4_2_hallucinations(design)
        results = [
            self._gr_4_1_explanations(design),
            *hallucination_results,
            self._gr_4_3_confidence(design, hallucination_results),
            self._gr_4_4_determinism_note(),
        ]
        self._log_results("validate_behavior", results)
        return results

    def _gr_4_1_explanations(self, design: Design) -> GuardrailResult:
        output = design.output
        if output is None or not output.decision_matrix or not output.decision_matrix.get("reasoning"):
            return GuardrailResult(
                status=GuardrailStatus.FLAG,
                severity=GuardrailSeverity.WARN,
                message="No overall reasoning was recorded for the selected architecture.",
                field="output.decision_matrix.reasoning",
                remediation="Ensure the design pipeline records a reasoning string for its selections.",
                source="GR 4.1 Choices Explained",
            )

        roadmap_phases = (output.implementation_roadmap or {}).get("phases", [])
        unexplained = [
            p.get("name", "unknown phase") for p in roadmap_phases if isinstance(p, dict) and not p.get("service")
        ]
        if unexplained:
            return GuardrailResult(
                status=GuardrailStatus.FLAG,
                severity=GuardrailSeverity.WARN,
                message=f"No service was selected/explained for: {', '.join(unexplained)}.",
                field="output.implementation_roadmap",
                remediation="Ensure every roadmap phase names the service chosen for it.",
                source="GR 4.1 Choices Explained",
            )
        return GuardrailResult(
            status=GuardrailStatus.PASS,
            severity=GuardrailSeverity.INFO,
            message="Every architecture choice has an accompanying explanation.",
            field=None,
            remediation=None,
            source="GR 4.1 Choices Explained",
        )

    def _gr_4_2_hallucinations(self, design: Design) -> List[GuardrailResult]:
        hallucinations = self._hallucination_detector.detect_hallucinations(design)
        if not hallucinations:
            return [
                GuardrailResult(
                    status=GuardrailStatus.PASS,
                    severity=GuardrailSeverity.INFO,
                    message="No unsourced factual claims were detected in the design.",
                    field=None,
                    remediation=None,
                    source="GR 4.2 No Hallucinated Claims",
                )
            ]
        return [
            GuardrailResult(
                status=GuardrailStatus.FLAG,
                severity=GuardrailSeverity.ERROR if h.confidence >= 0.7 else GuardrailSeverity.WARN,
                message=f'Unsourced claim: "{h.claim}" - {h.reason}',
                field=h.location,
                remediation="Remove the specific figure, or cite the document/API response it came from.",
                source="GR 4.2 Hallucinated Claim",
            )
            for h in hallucinations
        ]

    def _gr_4_3_confidence(self, design: Design, hallucination_results: List[GuardrailResult]) -> GuardrailResult:
        output = design.output
        base_confidence = (output.decision_matrix or {}).get("final_score") if output else None
        if base_confidence is None:
            return GuardrailResult(
                status=GuardrailStatus.FLAG,
                severity=GuardrailSeverity.WARN,
                message="No confidence score was recorded for this design.",
                field="output.decision_matrix.final_score",
                remediation="Ensure the design pipeline records a final_score.",
                source="GR 4.3 Design Confidence",
            )

        num_hallucinations = sum(1 for r in hallucination_results if r.source == "GR 4.2 Hallucinated Claim")
        penalty = min(0.1 * num_hallucinations, 0.5)
        effective_confidence = max(0.0, base_confidence - penalty)

        if effective_confidence >= 0.7:
            return GuardrailResult(
                status=GuardrailStatus.PASS,
                severity=GuardrailSeverity.INFO,
                message=f"Design confidence is {effective_confidence:.2f} (>= 0.70 threshold).",
                field="output.decision_matrix.final_score",
                remediation=None,
                source="GR 4.3 Design Confidence",
            )
        return GuardrailResult(
            status=GuardrailStatus.ESCALATE,
            severity=GuardrailSeverity.WARN,
            message=f"Design confidence is {effective_confidence:.2f}, below the 0.70 threshold.",
            field="output.decision_matrix.final_score",
            remediation="Review the design manually before proceeding; consider re-running with relaxed constraints.",
            source="GR 4.3 Design Confidence",
        )

    def _gr_4_4_determinism_note(self) -> GuardrailResult:
        return GuardrailResult(
            status=GuardrailStatus.PASS,
            severity=GuardrailSeverity.INFO,
            message=(
                "Determinism cannot be assessed from a single design; call check_determinism() to verify "
                "by re-running generation."
            ),
            field=None,
            remediation=None,
            source="GR 4.4 Determinism (not evaluated)",
        )

    def check_determinism(
        self, requirements: Requirement, design_fn: Callable[[Requirement], Design], runs: int = 2
    ) -> GuardrailResult:
        """Verify determinism (GR 4.4) by actually re-running design generation.

        Args:
            requirements: The requirements to generate a design from.
            design_fn: A callable (e.g. ``ArchitectAgent.design``) producing a
                Design for these requirements.
            runs: Number of times to regenerate and compare (>= 2).

        Returns:
            PASS if every run selects the same architecture path, FLAG otherwise.

        Raises:
            ValueError: If ``runs`` is less than 2.
        """
        if runs < 2:
            raise ValueError("runs must be >= 2 to check determinism.")

        paths = []
        for _ in range(runs):
            design = design_fn(requirements)
            path = (design.output.decision_matrix or {}).get("selected_path", []) if design.output else []
            paths.append(tuple(path))

        if len(set(paths)) == 1:
            return GuardrailResult(
                status=GuardrailStatus.PASS,
                severity=GuardrailSeverity.INFO,
                message=f"All {runs} runs selected the same architecture path: {' -> '.join(paths[0])}.",
                field=None,
                remediation=None,
                source="GR 4.4 Determinism",
            )
        return GuardrailResult(
            status=GuardrailStatus.FLAG,
            severity=GuardrailSeverity.WARN,
            message=f"Runs produced different architecture paths across {runs} attempts: {list(paths)}.",
            field=None,
            remediation="Investigate non-determinism (e.g. Claude sampling, RAG data changes between runs).",
            source="GR 4.4 Determinism",
        )

    # --- Shared helpers ---

    def _log_results(self, method: str, results: List[GuardrailResult]) -> None:
        for result in results:
            if result.status == GuardrailStatus.PASS:
                logger.info("[%s] %s: PASS - %s", method, result.source, result.message)
                continue
            log_fn = logger.error if result.severity == GuardrailSeverity.ERROR else logger.warning
            log_fn(
                "[%s] %s: %s (%s) - %s", method, result.source, result.status.value, result.severity.value, result.message
            )


_guardrail_validator: Optional[GuardrailValidator] = None


def get_guardrail_validator() -> GuardrailValidator:
    """Return a process-wide singleton GuardrailValidator (FastAPI dependency)."""
    global _guardrail_validator
    if _guardrail_validator is None:
        _guardrail_validator = GuardrailValidator()
    return _guardrail_validator

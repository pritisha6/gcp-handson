"""Checks a proposed architecture against regulatory compliance requirements."""
from typing import Any, Dict, List, Optional

from app.config import Settings, get_settings
from app.schemas.guardrail import GuardrailResult, GuardrailSeverity, GuardrailStatus
from app.services.rag_system import RAGSystem, get_rag_system
from app.utils.logger import get_logger

logger = get_logger(__name__)

SUPPORTED_REGULATIONS = {"SOC2", "HIPAA", "PCI-DSS", "GDPR", "ISO27001"}

# Illustrative approximate monthly cost to add a missing control.
_REMEDIATION_COST_BY_CONTROL: Dict[str, float] = {
    "encryption": 150.0,  # CMEK setup + ongoing KMS cost
    "data_residency": 400.0,  # regional replication / multi-region setup
}


class ComplianceValidator:
    """Checks a proposed architecture's controls against regulatory rules.

    Rules are loaded via ``RAGSystem.get_compliance_rules`` (Firestore
    ``compliance_rules`` collection, cached for 1h), so repeated checks for
    the same regulation don't repeatedly hit Firestore.
    """

    def __init__(self, rag_system: Optional[RAGSystem] = None, settings: Optional[Settings] = None) -> None:
        self._settings = settings or get_settings()
        self._rag_system = rag_system or get_rag_system()

    def check_compliance(self, architecture: Dict[str, Any], regulations: List[str]) -> List[GuardrailResult]:
        """Check an architecture's controls against each named regulation.

        Args:
            architecture: The proposed architecture's control state, e.g.
                ``{"encryption": True, "data_residency": "EU"}``.
            regulations: Regulation names to check, e.g. ``["GDPR", "HIPAA"]``.

        Returns:
            One ``GuardrailResult`` per regulation: PASS if all required
            controls are present, otherwise FLAG describing the gap and its
            estimated remediation cost. Unsupported regulation names produce
            an informational FLAG rather than raising.
        """
        return [self._check_one(regulation, architecture) for regulation in regulations]

    def _check_one(self, regulation: str, architecture: Dict[str, Any]) -> GuardrailResult:
        if regulation not in SUPPORTED_REGULATIONS:
            logger.warning("ComplianceValidator: unsupported regulation '%s'", regulation)
            return GuardrailResult(
                status=GuardrailStatus.FLAG,
                severity=GuardrailSeverity.INFO,
                message=f"'{regulation}' is not a regulation this validator has rules for.",
                field="compliance.regulations",
                remediation=f"Add rule data for '{regulation}' to the compliance_rules collection.",
                source="GR 2.3 Unsupported Regulation",
            )

        try:
            rule = self._rag_system.get_compliance_rules(regulation)
        except Exception:
            logger.exception("Compliance rule lookup failed for '%s'", regulation)
            rule = {}

        if not rule:
            return GuardrailResult(
                status=GuardrailStatus.FLAG,
                severity=GuardrailSeverity.WARN,
                message=f"No compliance rule data found for '{regulation}'; cannot verify controls.",
                field="compliance.regulations",
                remediation=f"Add a compliance_rules document for '{regulation}' and re-run validation.",
                source="GR 2.3 Compliance Rule Data Missing",
            )

        gaps: List[str] = []
        remediation_cost = 0.0

        if rule.get("requires_encryption") and not architecture.get("encryption", False):
            gaps.append("encryption at rest/in transit (CMEK)")
            remediation_cost += _REMEDIATION_COST_BY_CONTROL["encryption"]

        if rule.get("requires_data_residency"):
            allowed_regions = rule.get("allowed_regions") or []
            residency = architecture.get("data_residency")
            if not residency or (allowed_regions and residency not in allowed_regions):
                gaps.append(
                    f"data residency in {allowed_regions or 'an approved region'} (currently: {residency or 'unset'})"
                )
                remediation_cost += _REMEDIATION_COST_BY_CONTROL["data_residency"]

        if not gaps:
            return GuardrailResult(
                status=GuardrailStatus.PASS,
                severity=GuardrailSeverity.INFO,
                message=f"'{regulation}' controls are satisfied by the proposed architecture.",
                field="compliance.regulations",
                remediation=None,
                source=f"GR 2.3 Compliance Check ({regulation})",
            )

        logger.warning("Compliance gap for '%s': %s", regulation, gaps)
        return GuardrailResult(
            status=GuardrailStatus.FLAG,
            severity=GuardrailSeverity.ERROR,
            message=f"'{regulation}' requires {'; '.join(gaps)}, which the proposed architecture is missing.",
            field="compliance.regulations",
            remediation=(
                f"Add the missing control(s) (~${remediation_cost:,.0f}/mo) and route to security review "
                "before proceeding."
            ),
            source=f"GR 2.3 Compliance Gap ({regulation})",
        )


_compliance_validator: Optional[ComplianceValidator] = None


def get_compliance_validator() -> ComplianceValidator:
    """Return a process-wide singleton ComplianceValidator (FastAPI dependency)."""
    global _compliance_validator
    if _compliance_validator is None:
        _compliance_validator = ComplianceValidator()
    return _compliance_validator

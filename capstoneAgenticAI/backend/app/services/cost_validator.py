"""Validates a proposed architecture's estimated cost against budget, with ROI justification for overages."""
from typing import Optional

from app.schemas.guardrail import GuardrailResult, GuardrailSeverity, GuardrailStatus
from app.utils.logger import get_logger

logger = get_logger(__name__)

# GR 2.2 tiers, as a fraction over budget_cap.
_WARN_OVERAGE_THRESHOLD = 0.10  # <=10% over: negotiable
_ESCALATE_OVERAGE_THRESHOLD = 0.50  # 10-50% over: needs approval; >50%: escalate to CFO


class CostValidator:
    """Compares actual cost to budget and justifies overages via ROI when possible."""

    def validate_cost(
        self,
        total_cost: float,
        budget_cap: float,
        current_state_cost: Optional[float] = None,
    ) -> GuardrailResult:
        """Compare a proposed architecture's cost against the budget cap.

        Args:
            total_cost: Estimated total monthly cost of the proposed design (USD).
            budget_cap: The stated monthly budget cap (USD).
            current_state_cost: Optional estimated monthly cost of the current/
                legacy system. When provided, used to compute
                ``ROI = business_benefits / design_cost`` where
                ``business_benefits = current_state_cost - total_cost``, per
                the standard ROI justification for budget overages.

        Returns:
            A single ``GuardrailResult`` summarizing the cost check.
        """
        if budget_cap <= 0:
            return GuardrailResult(
                status=GuardrailStatus.FLAG,
                severity=GuardrailSeverity.WARN,
                message="No budget cap was provided; cost cannot be evaluated against a limit.",
                field="budget.monthly_cap_usd",
                remediation="Provide a monthly budget cap to enable cost validation.",
                source="GR 2.2 Cost Validation Skipped (no budget)",
            )

        if total_cost <= budget_cap:
            return GuardrailResult(
                status=GuardrailStatus.PASS,
                severity=GuardrailSeverity.INFO,
                message=f"Estimated cost (${total_cost:,.0f}/mo) is within the ${budget_cap:,.0f}/mo budget.",
                field="budget.monthly_cap_usd",
                remediation=None,
                source="GR 2.2 Cost Within Budget",
            )

        overage = total_cost - budget_cap
        overage_ratio = overage / budget_cap
        roi_note = self._roi_justification(total_cost, current_state_cost)

        if overage_ratio <= _WARN_OVERAGE_THRESHOLD:
            logger.info("Cost %.1f%% over budget (WARN tier)", overage_ratio * 100)
            return GuardrailResult(
                status=GuardrailStatus.FLAG,
                severity=GuardrailSeverity.WARN,
                message=(
                    f"Estimated cost (${total_cost:,.0f}/mo) is {overage_ratio:.0%} over the "
                    f"${budget_cap:,.0f}/mo budget (within the 10% negotiable range)."
                ),
                field="budget.monthly_cap_usd",
                remediation=(
                    f"Negotiate a budget increase to ${total_cost:,.0f}/mo, or trim ${overage:,.0f}/mo of "
                    f"cost.{roi_note}"
                ),
                source="GR 2.2 Cost Over Budget (WARN)",
            )

        if overage_ratio <= _ESCALATE_OVERAGE_THRESHOLD:
            logger.warning("Cost %.1f%% over budget (CAUTION tier, needs approval)", overage_ratio * 100)
            return GuardrailResult(
                status=GuardrailStatus.ESCALATE,
                severity=GuardrailSeverity.WARN,
                message=(
                    f"Estimated cost (${total_cost:,.0f}/mo) is {overage_ratio:.0%} over the "
                    f"${budget_cap:,.0f}/mo budget (10-50% over: requires approval)."
                ),
                field="budget.monthly_cap_usd",
                remediation=f"Obtain budget-owner approval to increase the cap to ${total_cost:,.0f}/mo.{roi_note}",
                source="GR 2.2 Cost Over Budget (CAUTION)",
            )

        logger.warning("Cost %.1f%% over budget (ERROR tier, escalate to CFO)", overage_ratio * 100)
        return GuardrailResult(
            status=GuardrailStatus.ESCALATE,
            severity=GuardrailSeverity.ERROR,
            message=(
                f"Estimated cost (${total_cost:,.0f}/mo) is {overage_ratio:.0%} over the "
                f"${budget_cap:,.0f}/mo budget (>50% over: requires CFO sign-off)."
            ),
            field="budget.monthly_cap_usd",
            remediation=(
                f"Escalate to CFO for sign-off on ${total_cost:,.0f}/mo, or substantially reduce "
                f"scope.{roi_note}"
            ),
            source="GR 2.2 Cost Over Budget (ERROR - CFO escalation)",
        )

    def _roi_justification(self, total_cost: float, current_state_cost: Optional[float]) -> str:
        """Build an ROI justification snippet: ROI = business_benefits / design_cost.

        ``business_benefits`` is approximated as the cost avoided by not
        continuing to run the current/legacy system
        (``current_state_cost - total_cost``, when positive).
        """
        if current_state_cost is None or total_cost <= 0:
            return " ROI could not be computed (no current-system cost baseline provided)."

        business_benefits = current_state_cost - total_cost
        if business_benefits <= 0:
            return (
                f" The proposed design (${total_cost:,.0f}/mo) costs more than continuing the current "
                f"system (${current_state_cost:,.0f}/mo); ROI is not favorable on cost alone."
            )

        roi = business_benefits / total_cost
        return (
            f" ROI: replacing the ~${current_state_cost:,.0f}/mo current system saves ~${business_benefits:,.0f}"
            f"/mo, an ROI of {roi:.1f}x on the ${total_cost:,.0f}/mo design cost."
        )


_cost_validator: Optional[CostValidator] = None


def get_cost_validator() -> CostValidator:
    """Return a process-wide singleton CostValidator (FastAPI dependency)."""
    global _cost_validator
    if _cost_validator is None:
        _cost_validator = CostValidator()
    return _cost_validator

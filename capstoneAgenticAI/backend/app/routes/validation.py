"""Endpoints for running guardrail validation directly (outside the full design pipeline)."""
from typing import List

from fastapi import APIRouter, Depends
from starlette.concurrency import run_in_threadpool

from app.schemas.design import Design, Requirement
from app.schemas.guardrail import GuardrailResult
from app.services.guardrail_validator import GuardrailValidator, get_guardrail_validator

router = APIRouter(prefix="/api/validate", tags=["validation"])


@router.post(
    "/requirements",
    response_model=List[GuardrailResult],
    summary="Run SET 1 input-validation guardrails against a Requirement",
)
async def validate_requirements(
    requirements: Requirement,
    validator: GuardrailValidator = Depends(get_guardrail_validator),
) -> List[GuardrailResult]:
    """Check completeness, contradictions, and realistic constraints (GR 1.1-1.3)."""
    return await run_in_threadpool(validator.validate_requirements, requirements)


@router.post(
    "/design",
    response_model=List[GuardrailResult],
    summary="Run SET 3 + SET 4 guardrails against a Design",
)
async def validate_design(
    design: Design,
    validator: GuardrailValidator = Depends(get_guardrail_validator),
) -> List[GuardrailResult]:
    """Check design coverage/cost/compliance/quotas/DR (GR 3.x) and behavioral guardrails (GR 4.x)."""
    design_results = await run_in_threadpool(validator.validate_design, design)
    behavior_results = await run_in_threadpool(validator.validate_behavior, design)
    return design_results + behavior_results

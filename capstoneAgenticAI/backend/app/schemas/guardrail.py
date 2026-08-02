"""Schemas for the safety guardrail system.

Kept alongside the other domain schemas in ``app/schemas`` (rather than a
separate top-level ``models/`` package) to match this codebase's existing
convention of collecting all Pydantic models there.
"""
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class GuardrailStatus(str, Enum):
    """Action to take as a result of a guardrail check.

    PASS     - no issues, proceed normally.
    FLAG     - issue detected but not blocking; mark for review, proceed.
    ESCALATE - human decision required; pause until approved.
    STOP     - fatal error; cannot proceed, request constraint adjustment.
    """

    PASS = "PASS"
    FLAG = "FLAG"
    ESCALATE = "ESCALATE"
    STOP = "STOP"


class GuardrailSeverity(str, Enum):
    """How serious the underlying issue is, independent of the action taken."""

    INFO = "INFO"
    WARN = "WARN"
    ERROR = "ERROR"


class GuardrailResult(BaseModel):
    """The outcome of a single guardrail check."""

    status: GuardrailStatus = Field(..., description="Action to take: PASS, FLAG, ESCALATE, or STOP")
    severity: GuardrailSeverity = Field(..., description="How serious the underlying issue is")
    message: str = Field(..., description="Human-readable explanation")
    field: Optional[str] = Field(default=None, description="Which requirement/constraint field this concerns")
    remediation: Optional[str] = Field(default=None, description="How to fix it, e.g. 'increase budget to $12K'")
    source: str = Field(..., description="Which guardrail triggered this, e.g. 'GR 2.2 Cost Over Budget'")


class Hallucination(BaseModel):
    """A design claim that could not be traced back to a document, API response, or database record."""

    claim: str = Field(..., description="The unsourced claim as it appears in the design")
    location: str = Field(..., description="Where in the design this claim was found, e.g. 'decision_matrix.reasoning'")
    reason: str = Field(..., description="Why this claim is considered unsourced/unverifiable")
    confidence: float = Field(..., ge=0, le=1, description="Confidence that this is genuinely a hallucination")

"""Request and response models for the public HTTP API.

Kept separate from ``app.schemas.design`` (the domain/storage models) so the
wire format can evolve independently of the persisted document shape.
"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.schemas.design import Design, DesignOutput, DesignStatus, Requirement
from app.schemas.guardrail import GuardrailResult


# --- Requests ---


class CreateDesignRequest(BaseModel):
    """Body for POST /api/designs/create."""

    project_name: str = Field(..., min_length=1, description="Name of the project this design belongs to")
    requirements: Requirement = Field(..., description="Requirements to generate a design from")


class UpdateDesignRequest(BaseModel):
    """Body for PATCH /api/designs/{design_id}.

    All fields optional; only provided fields are updated.
    """

    project_name: Optional[str] = Field(default=None, min_length=1)
    requirements: Optional[Requirement] = Field(default=None)
    status: Optional[DesignStatus] = Field(default=None)
    output: Optional[DesignOutput] = Field(default=None)


# --- Responses ---


class CreateDesignResponse(BaseModel):
    """Response for POST /api/designs/create.

    Minimal payload returned immediately; the full design is generated
    asynchronously and can be polled via GET /api/designs/{design_id}.
    """

    id: str = Field(..., description="Unique design identifier")
    project_name: str
    status: DesignStatus
    created_at: datetime


class DesignResponse(BaseModel):
    """Full design representation returned by GET/PATCH endpoints."""

    id: str
    project_name: str
    requirements: Requirement
    status: DesignStatus
    output: Optional[DesignOutput] = None
    validation_results: List[GuardrailResult] = Field(default_factory=list)
    generation_seconds: Optional[float] = None
    api_calls_count: int = 0
    api_cost_usd: float = 0.0
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_design(cls, design: Design) -> "DesignResponse":
        return cls(**design.model_dump())


class PaginationMeta(BaseModel):
    """Pagination metadata attached to list responses."""

    skip: int = Field(..., ge=0)
    limit: int = Field(..., ge=1)
    total: int = Field(..., ge=0, description="Total number of matching records")


class ListDesignsResponse(BaseModel):
    """Response for GET /api/designs."""

    items: List[DesignResponse]
    pagination: PaginationMeta


class DeleteDesignResponse(BaseModel):
    """Response for DELETE /api/designs/{design_id} (soft delete)."""

    id: str
    status: DesignStatus
    deleted: bool = True


# --- Errors ---


class ErrorDetail(BaseModel):
    """Machine-readable error payload nested inside error responses."""

    code: str = Field(..., description="Stable machine-readable error code")
    message: str = Field(..., description="Human-readable error message")
    details: Dict[str, Any] = Field(default_factory=dict, description="Additional structured context")


class ErrorResponse(BaseModel):
    """Standard error envelope returned for all error responses."""

    error: ErrorDetail
    correlation_id: Optional[str] = Field(
        default=None, description="Request correlation id for tracing this error in logs"
    )


class BadRequestResponse(ErrorResponse):
    """400 Bad Request response schema, used for OpenAPI documentation."""


class NotFoundResponse(ErrorResponse):
    """404 Not Found response schema, used for OpenAPI documentation."""


class InternalErrorResponse(ErrorResponse):
    """500 Internal Server Error response schema, used for OpenAPI documentation."""

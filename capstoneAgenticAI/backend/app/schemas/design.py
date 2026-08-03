"""Core domain models for the ETL Design Agent.

These models describe the shape of a design request (Requirement), the
generated artifact (Design / DesignOutput), and the sign-off workflow
(Approval). They are used both as API request/response bodies and as the
Firestore document schema (via ``model_dump``/``model_validate``).
"""
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

from app.schemas.guardrail import GuardrailResult


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return str(uuid.uuid4())


class DataSourceType(str, Enum):
    """Supported categories of upstream data sources."""

    DB = "DB"
    API = "API"
    FILE = "File"
    MESSAGING = "Messaging"


class DesignStatus(str, Enum):
    """Lifecycle status of a Design as it moves through generation."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    DELETED = "deleted"


class ApprovalDecision(str, Enum):
    """Individual approver's decision on a design."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class FinalStatus(str, Enum):
    """Aggregate outcome of the approval workflow."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class DataSource(BaseModel):
    """A single upstream data source feeding the ETL pipeline."""

    name: str = Field(..., min_length=1, description="Human-readable name of the data source")
    type: DataSourceType = Field(..., description="Category of the data source")
    size_gb: float = Field(..., ge=0, description="Approximate data volume in gigabytes")
    throughput_records_sec: float = Field(
        ..., ge=0, description="Expected sustained throughput in records/second"
    )


class Performance(BaseModel):
    """Performance and SLA requirements for the pipeline."""

    latency_sla_minutes: float = Field(..., ge=0, description="End-to-end latency SLA in minutes")
    peak_throughput_msgs_sec: float = Field(
        ..., ge=0, description="Peak expected throughput in messages/second"
    )
    data_freshness: str = Field(
        ..., min_length=1, description="Required data freshness, e.g. 'real-time', '15min', 'daily'"
    )
    p95_latency_minutes: float = Field(..., ge=0, description="95th percentile latency target in minutes")


class Budget(BaseModel):
    """Cost constraints for the resulting architecture."""

    monthly_cap_usd: float = Field(..., ge=0, description="Maximum acceptable monthly cost")
    currency: str = Field(default="USD", min_length=3, max_length=3, description="ISO 4217 currency code")

    @field_validator("currency")
    @classmethod
    def uppercase_currency(cls, value: str) -> str:
        return value.upper()


class Team(BaseModel):
    """Team composition and skill set available to build/operate the pipeline."""

    size: int = Field(..., ge=1, description="Number of engineers available")
    skills: List[str] = Field(default_factory=list, description="Relevant skills, e.g. ['python', 'dataflow']")


class Compliance(BaseModel):
    """Regulatory and data-governance constraints."""

    data_types: List[str] = Field(default_factory=list, description="Categories of data handled, e.g. ['PII', 'PHI']")
    regulations: List[str] = Field(default_factory=list, description="Applicable regulations, e.g. ['GDPR', 'HIPAA']")
    data_residency: Optional[str] = Field(default=None, description="Required data residency region, e.g. 'EU'")
    encryption: bool = Field(default=True, description="Whether encryption at rest/in transit is required")


class Requirement(BaseModel):
    """Full set of inputs describing a desired ETL pipeline."""

    data_sources: List[DataSource] = Field(..., min_length=1, description="Upstream data sources")
    performance: Performance = Field(..., description="Performance and SLA requirements")
    budget: Budget = Field(..., description="Cost constraints")
    team: Team = Field(..., description="Team composition")
    compliance: Compliance = Field(..., description="Regulatory constraints")
    context: Optional[str] = Field(
        default=None, description="Free-form additional context or notes from the requester"
    )


class DesignOutput(BaseModel):
    """Generated artifacts produced by the design agent."""

    architecture_diagram: Optional[str] = Field(
        default=None, description="Diagram representation, e.g. Mermaid source or a storage URI"
    )
    decision_matrix: Optional[Dict] = Field(
        default=None, description="Structured comparison of architecture options and rationale"
    )
    cost_analysis: Optional[Dict] = Field(default=None, description="Projected cost breakdown")
    compliance_checklist: Optional[Dict] = Field(
        default=None, description="Compliance requirements mapped to how the design satisfies them"
    )
    implementation_roadmap: Optional[Dict] = Field(
        default=None, description="Phased plan for implementing the design"
    )


class Design(BaseModel):
    """A design request together with its (possibly in-progress) output."""

    id: str = Field(default_factory=_new_id, description="Unique design identifier")
    project_name: str = Field(..., min_length=1, description="Name of the project this design belongs to")
    requirements: Requirement = Field(..., description="Input requirements for this design")
    status: DesignStatus = Field(default=DesignStatus.PENDING, description="Current lifecycle status")
    output: Optional[DesignOutput] = Field(default=None, description="Generated design output, once available")
    validation_results: List[GuardrailResult] = Field(
        default_factory=list, description="Guardrail check results from the validation cycle"
    )
    generation_seconds: Optional[float] = Field(
        default=None, ge=0, description="Wall-clock time the ArchitectAgent took to generate this design"
    )
    api_calls_count: int = Field(default=0, ge=0, description="Groq/OpenAI API calls made while generating this design")
    api_cost_usd: float = Field(default=0.0, ge=0, description="Estimated API spend while generating this design")
    created_at: datetime = Field(default_factory=_utcnow, description="Creation timestamp (UTC)")
    updated_at: datetime = Field(default_factory=_utcnow, description="Last update timestamp (UTC)")


class ApprovalEntry(BaseModel):
    """A single approver's decision and optional comment."""

    decision: ApprovalDecision = Field(default=ApprovalDecision.PENDING)
    comment: Optional[str] = Field(default=None)
    decided_at: Optional[datetime] = Field(default=None)


class Approvals(BaseModel):
    """Per-role sign-off status for a design."""

    engineer: ApprovalEntry = Field(default_factory=ApprovalEntry)
    architect: ApprovalEntry = Field(default_factory=ApprovalEntry)
    cfo: ApprovalEntry = Field(default_factory=ApprovalEntry)
    security: ApprovalEntry = Field(default_factory=ApprovalEntry)
    ops: ApprovalEntry = Field(default_factory=ApprovalEntry)


class Approval(BaseModel):
    """Aggregate approval workflow state for a design."""

    design_id: str = Field(..., description="Identifier of the design being approved")
    approvals: Approvals = Field(default_factory=Approvals, description="Per-role approval decisions")
    final_status: FinalStatus = Field(default=FinalStatus.PENDING, description="Aggregate approval outcome")
    final_decision: Optional[str] = Field(
        default=None, description="Free-form summary explaining the final decision"
    )

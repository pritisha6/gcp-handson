"""Firestore collection names and document schema documentation.

Firestore is schemaless, so these are not ORM models — they are the
single source of truth for collection names plus a documented shape for
each document type, used to keep reads/writes across the codebase
consistent.
"""
from enum import Enum
from typing import Any, Dict, TypedDict


class Collection(str, Enum):
    """Firestore top-level collection names used by this service."""

    DESIGNS = "designs"
    REQUIREMENTS = "requirements"
    APPROVALS = "approvals"
    COMPLIANCE_RULES = "compliance_rules"
    DESIGN_PRECEDENTS = "design_precedents"
    TOT_SEARCH_STATE = "tot_search_state"
    DESIGN_METRICS = "design_metrics"
    AUDIT_TRAIL = "audit_trail"


class DesignDocument(TypedDict, total=False):
    """Document shape for the ``designs`` collection.

    Mirrors ``app.schemas.design.Design``. ``requirements`` and ``output``
    are stored as nested maps (the serialized Pydantic models).
    """

    id: str
    project_name: str
    requirements: Dict[str, Any]
    status: str
    output: Dict[str, Any]
    validation_results: list
    created_at: Any  # google.cloud.firestore.SERVER_TIMESTAMP or datetime
    updated_at: Any
    deleted: bool


class RequirementDocument(TypedDict, total=False):
    """Document shape for the ``requirements`` collection.

    Stores requirements independently of a design when reused across
    multiple design iterations (e.g. RAG precedent matching).
    """

    id: str
    design_id: str
    data_sources: list
    performance: Dict[str, Any]
    budget: Dict[str, Any]
    team: Dict[str, Any]
    compliance: Dict[str, Any]
    context: str
    created_at: Any


class ApprovalDocument(TypedDict, total=False):
    """Document shape for the ``approvals`` collection.

    Mirrors ``app.schemas.design.Approval``, keyed by ``design_id``.
    """

    design_id: str
    approvals: Dict[str, Any]
    final_status: str
    final_decision: str
    updated_at: Any


class ComplianceRuleDocument(TypedDict, total=False):
    """Document shape for the ``compliance_rules`` collection.

    Reference data used by the design agent to validate a design against
    a given regulation (e.g. GDPR, HIPAA).
    """

    id: str
    regulation: str
    description: str
    requires_encryption: bool
    requires_data_residency: bool
    allowed_regions: list
    applicable_data_types: list


class DesignPrecedentDocument(TypedDict, total=False):
    """Document shape for the ``design_precedents`` collection.

    Historical (requirement, design) pairs used as few-shot / RAG
    precedents for future design generation.
    """

    id: str
    design_id: str
    workload_type: str  # e.g. "batch-etl", "streaming-analytics"; used to filter precedents
    requirement_summary: str
    embedding_id: str  # id of the corresponding vector in Pinecone
    architecture_summary: str
    outcome_notes: str
    created_at: Any


class ToTSearchStateDocument(TypedDict, total=False):
    """Document shape for the ``tot_search_state`` collection.

    Mirrors ``app.schemas.tot.ToTSearchState``, keyed by ``design_id``. One
    document per in-progress or completed Tree-of-Thought search.
    """

    design_id: str
    current_level: int
    candidates_at_level: list
    all_nodes: list
    best_complete_paths: list
    requirements_snapshot: Dict[str, Any]
    updated_at: Any


class DesignMetricsDocument(TypedDict, total=False):
    """Document shape for the ``design_metrics`` collection.

    One document per design, keyed by ``design_id``. Mirrors
    ``app.schemas.metrics.DesignMetrics``; computed and written once by
    ``MetricsService`` when a design finishes generating.
    """

    design_id: str
    project_name: str
    status: str
    requirement_coverage_pct: float
    compliance_pass_rate_pct: float
    approval_rate_pct: float
    total_cost_usd: float
    generation_seconds: float
    api_calls_count: int
    api_cost_usd: float
    hallucination_count: int
    created_at: Any
    updated_at: Any


class AuditTrailDocument(TypedDict, total=False):
    """Document shape for the ``audit_trail`` collection.

    Append-only: entries are created via ``AuditTrailService.record_event``
    and never updated or deleted, for compliance/non-repudiation.
    """

    design_id: str
    event_type: str  # e.g. "design_created", "design_completed", "approval_submitted", "guardrail_triggered"
    stakeholder: str
    details: Dict[str, Any]
    recorded_at: Any

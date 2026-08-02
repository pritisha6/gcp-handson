"""Schemas for the Tree-of-Thought architecture search and the ReAct agent."""
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from app.schemas.design import Design

LAYERS: tuple = ("ingestion", "processing", "storage", "serving")
Layer = Literal["ingestion", "processing", "storage", "serving"]


class Candidate(BaseModel):
    """A single candidate service proposed for one architecture layer."""

    service: str = Field(..., min_length=1, description="Service name, e.g. 'Pub/Sub' or 'Kafka on GKE'")
    rationale: str = Field(..., description="Why this service fits the given requirements")
    estimated_cost: float = Field(..., ge=0, description="Rough estimated monthly cost in USD")
    tradeoffs: List[str] = Field(default_factory=list, description="Known downsides/trade-offs")
    feasibility: float = Field(..., ge=0, le=1, description="Self-assessed technical feasibility (0-1)")


class ScoreBreakdown(BaseModel):
    """Per-criterion scores (0-1) produced by the CriticEvaluator."""

    latency: float = Field(..., ge=0, le=1)
    cost: float = Field(..., ge=0, le=1)
    ops: float = Field(..., ge=0, le=1)
    compliance: float = Field(..., ge=0, le=1)


class EvalResult(BaseModel):
    """CriticEvaluator's scored assessment of one candidate."""

    candidate: Candidate
    scores: ScoreBreakdown
    final_score: float = Field(..., ge=0, le=1)
    reasoning: str
    confidence: float = Field(..., ge=0, le=1)


class TreeNodeState(BaseModel):
    """A single node in the ToT search tree: one candidate chosen at one layer of one path."""

    id: str
    design_id: str
    level: int = Field(..., ge=0, le=4, description="0=root, 1=ingestion, 2=processing, 3=storage, 4=serving")
    layer: Optional[Layer] = None
    candidate: Optional[Candidate] = None
    eval_result: Optional[EvalResult] = None
    parent_id: Optional[str] = None
    path: List[str] = Field(default_factory=list, description="Service names selected so far, root to this node")
    cumulative_score: float = Field(default=0.0, ge=0, le=1)
    pruned: bool = False
    pruned_reason: Optional[str] = None


class ToTSearchState(BaseModel):
    """Full persisted state of one Tree-of-Thought search, for durability/resumption."""

    design_id: str
    current_level: int = Field(default=0, ge=0, le=4)
    candidates_at_level: List[TreeNodeState] = Field(default_factory=list)
    all_nodes: List[TreeNodeState] = Field(default_factory=list)
    best_complete_paths: List[TreeNodeState] = Field(default_factory=list)
    requirements_snapshot: Dict[str, Any] = Field(default_factory=dict)


class ArchitectureSearchResult(BaseModel):
    """Final (or partial) output of ``TreeOfThoughtEngine.search()``."""

    design_id: str
    status: Literal["completed", "escalated", "partial"]
    termination_reason: str
    architecture_path: List[str]
    services: Dict[str, str]
    final_score: float = Field(..., ge=0, le=1)
    reasoning: str
    alternatives: List[Dict[str, Any]] = Field(default_factory=list)


class ProgressEvent(BaseModel):
    """One streamed progress update from ``ArchitectAgent.stream_design()``."""

    cycle: str = Field(..., description="Human-readable cycle group name, e.g. 'Discovery (Cycles 1-3)'")
    message: str
    data: Dict[str, Any] = Field(default_factory=dict, description="Partial agent state produced by this cycle")
    design: Optional[Design] = Field(default=None, description="Populated only on the final event")

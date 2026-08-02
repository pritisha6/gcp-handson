"""Schemas for the RAG retrieval layer."""
from typing import Any, Dict

from pydantic import BaseModel, Field


class Document(BaseModel):
    """A retrieved document chunk, scored by relevance to a query."""

    id: str = Field(..., description="Vector/document identifier")
    text: str = Field(..., description="Retrieved chunk text")
    score: float = Field(..., description="Similarity score (higher is more relevant)")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Source metadata for this chunk")

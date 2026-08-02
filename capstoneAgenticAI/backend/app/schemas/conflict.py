"""Schemas for requirement conflict detection."""
from enum import Enum
from typing import List

from pydantic import BaseModel, Field


class ConflictSeverity(str, Enum):
    """How serious a detected requirement conflict is."""

    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class Conflict(BaseModel):
    """A detected contradiction between two or more requirement fields."""

    type: str = Field(..., description="Machine-readable conflict category, e.g. 'latency_vs_freshness'")
    severity: ConflictSeverity = Field(..., description="How serious the conflict is")
    fields_involved: List[str] = Field(..., description="Requirement field paths implicated in this conflict")
    description: str = Field(..., description="Human-readable explanation of the contradiction")
    suggested_resolution: str = Field(..., description="Recommended way to resolve the conflict")

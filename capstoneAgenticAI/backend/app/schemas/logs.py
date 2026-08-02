"""Schemas for the recent-logs query API."""
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class LogEntry(BaseModel):
    """One structured log entry, as returned by GET /api/logs."""

    timestamp: str
    level: str
    category: Optional[str] = None
    correlation_id: Optional[str] = None
    message: str
    details: Dict[str, Any] = Field(default_factory=dict)

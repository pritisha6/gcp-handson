"""Structured (JSON) logging service with category-specific log methods.

Builds on ``app.utils.logger`` (which configures the root logger's
handlers, JSON formatting, and correlation-id context var) rather than
replacing it: this module adds a structured-payload layer and
category-specific convenience methods on top of the same handlers, so a
call like ``log_decision(...)`` ends up as one well-shaped JSON line
locally and one queryable ``jsonPayload`` entry in Cloud Logging.
"""
import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from app.schemas.logs import LogEntry
from app.utils.logger import correlation_id_var, get_logger


class LogCategory(str, Enum):
    """The five log categories this system distinguishes."""

    DECISION = "decision"
    DATA_RETRIEVAL = "data_retrieval"
    CONSTRAINT_VIOLATION = "constraint_violation"
    API_CALL = "api_call"
    USER_INTERACTION = "user_interaction"


def _now_iso_ms() -> str:
    """Current UTC time as an ISO 8601 string with millisecond precision."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class LoggingService:
    """Emits structured JSON log entries for decisions, retrieval, violations, API calls, and user actions.

    Every entry carries: ``timestamp`` (ms precision), ``category``,
    ``level``, ``correlation_id`` (from the active request context, if
    any), ``message``, and an arbitrary ``details`` payload.
    """

    def __init__(self, component: str = "app") -> None:
        self._logger = get_logger(f"etl_design_agent.{component}")

    def _emit(self, level: int, category: LogCategory, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        payload = {
            "timestamp": _now_iso_ms(),
            "category": category.value,
            "level": logging.getLevelName(level),
            "correlation_id": correlation_id_var.get(),
            "message": message,
            "details": {k: v for k, v in (details or {}).items() if v is not None},
        }
        # `structured` drives the local JSON console formatter; `json_fields`
        # is the key google-cloud-logging's handler looks for to populate
        # Cloud Logging's structured jsonPayload. Both point at the same dict.
        self._logger.log(level, message, extra={"structured": payload, "json_fields": payload})

    # --- Category-specific convenience methods ---

    def log_decision(self, message: str, *, design_id: Optional[str] = None, **details: Any) -> None:
        """Log agent reasoning or a decision made (e.g. a Tree-of-Thought service selection)."""
        self._emit(logging.INFO, LogCategory.DECISION, message, {"design_id": design_id, **details})

    def log_data_retrieval(self, message: str, *, source: str, query: Optional[str] = None, **details: Any) -> None:
        """Log a RAG/document/pricing/compliance-rule retrieval."""
        self._emit(logging.INFO, LogCategory.DATA_RETRIEVAL, message, {"source": source, "query": query, **details})

    def log_constraint_violation(
        self,
        message: str,
        *,
        guardrail_source: str,
        severity: str = "WARN",
        design_id: Optional[str] = None,
        **details: Any,
    ) -> None:
        """Log a guardrail trigger (FLAG/ESCALATE/STOP)."""
        level = logging.ERROR if severity in ("ERROR", "STOP") else logging.WARNING
        self._emit(
            level,
            LogCategory.CONSTRAINT_VIOLATION,
            message,
            {"guardrail_source": guardrail_source, "severity": severity, "design_id": design_id, **details},
        )

    def log_api_call(
        self,
        provider: str,
        *,
        operation: str,
        duration_ms: Optional[float] = None,
        success: bool = True,
        **details: Any,
    ) -> None:
        """Log an outbound call to GCP, Groq, OpenAI, Pinecone, etc."""
        level = logging.INFO if success else logging.ERROR
        message = f"{provider} {operation} {'succeeded' if success else 'failed'}"
        self._emit(
            level,
            LogCategory.API_CALL,
            message,
            {"provider": provider, "operation": operation, "duration_ms": duration_ms, "success": success, **details},
        )

    def log_user_interaction(self, message: str, *, action: str, user: Optional[str] = None, **details: Any) -> None:
        """Log a user-facing action: file upload, approval submission, design request, etc."""
        self._emit(logging.INFO, LogCategory.USER_INTERACTION, message, {"action": action, "user": user, **details})

    # --- Generic escape hatches ---

    def debug(self, category: LogCategory, message: str, **details: Any) -> None:
        self._emit(logging.DEBUG, category, message, details)

    def error(self, category: LogCategory, message: str, **details: Any) -> None:
        self._emit(logging.ERROR, category, message, details)

    # --- Querying ---

    def query_recent_logs(
        self,
        *,
        level: Optional[str] = None,
        category: Optional[str] = None,
        correlation_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[LogEntry]:
        """Query recent structured logs from Cloud Logging.

        Requires a reachable GCP project with Cloud Logging enabled and
        valid Application Default Credentials; returns an empty list (with
        a warning logged) if Cloud Logging can't be queried, e.g. in local
        development without ADC configured.

        Args:
            level: Minimum severity, e.g. "WARNING".
            category: Restrict to one ``LogCategory`` value.
            correlation_id: Restrict to logs from one request/trace.
            limit: Maximum number of entries to return.

        Returns:
            Matching entries, most recent first (possibly empty).
        """
        try:
            import google.cloud.logging as cloud_logging

            client = cloud_logging.Client()
            filter_parts = []
            if level:
                filter_parts.append(f'severity>="{level.upper()}"')
            if category:
                filter_parts.append(f'jsonPayload.category="{category}"')
            if correlation_id:
                filter_parts.append(f'jsonPayload.correlation_id="{correlation_id}"')
            filter_str = " AND ".join(filter_parts) if filter_parts else None

            entries = client.list_entries(filter_=filter_str, order_by=cloud_logging.DESCENDING, max_results=limit)
            results: List[LogEntry] = []
            for entry in entries:
                payload = entry.payload if isinstance(entry.payload, dict) else {"message": str(entry.payload)}
                results.append(
                    LogEntry(
                        timestamp=entry.timestamp.isoformat() if entry.timestamp else _now_iso_ms(),
                        level=payload.get("level") or (entry.severity or "INFO"),
                        category=payload.get("category"),
                        correlation_id=payload.get("correlation_id"),
                        message=payload.get("message", ""),
                        details=payload.get("details", {}),
                    )
                )
            return results
        except Exception:
            self._logger.warning(
                "Could not query Cloud Logging for recent logs (is ADC/the project configured?)", exc_info=True
            )
            return []


_logging_service: Optional[LoggingService] = None


def get_logging_service() -> LoggingService:
    """Return a process-wide singleton LoggingService (FastAPI dependency)."""
    global _logging_service
    if _logging_service is None:
        _logging_service = LoggingService()
    return _logging_service

"""Immutable audit trail of design decisions and approvals, for compliance/non-repudiation."""
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from google.api_core import exceptions as gcp_exceptions
from google.cloud import firestore

from app.config import Settings, get_settings
from app.db.models import Collection
from app.utils.errors import FirestoreOperationError
from app.utils.logger import get_logger

logger = get_logger(__name__)


class AuditTrailService:
    """Append-only log of design decisions/approvals, queryable for compliance review.

    Only two operations are exposed: ``record_event`` (create) and
    ``query`` (read). Entries are never updated or deleted once written,
    which is the point — an audit trail that can be edited after the fact
    isn't one.
    """

    def __init__(self, firestore_client: Optional[firestore.Client] = None, settings: Optional[Settings] = None) -> None:
        self._settings = settings or get_settings()
        self._client = firestore_client or firestore.Client(
            project=self._settings.GCP_PROJECT_ID, database=self._settings.FIRESTORE_DATABASE
        )
        self._collection = self._client.collection(Collection.AUDIT_TRAIL.value)

    def record_event(
        self,
        design_id: str,
        event_type: str,
        *,
        stakeholder: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Append one immutable audit event.

        Args:
            design_id: The design this event concerns.
            event_type: e.g. "design_created", "design_completed",
                "approval_submitted", "guardrail_triggered".
            stakeholder: The role/person responsible for this event, if applicable.
            details: Arbitrary structured context.

        Returns:
            The new audit entry's document id.

        Raises:
            FirestoreOperationError: On an unexpected Firestore failure.
        """
        entry = {
            "design_id": design_id,
            "event_type": event_type,
            "stakeholder": stakeholder,
            "details": details or {},
            "recorded_at": datetime.now(timezone.utc),
        }
        try:
            _, doc_ref = self._collection.add(entry)
            logger.info("Audit event recorded: design=%s event=%s stakeholder=%s", design_id, event_type, stakeholder)
            return doc_ref.id
        except gcp_exceptions.GoogleAPICallError as exc:
            logger.exception("Failed to record audit event '%s' for design '%s'", event_type, design_id)
            raise FirestoreOperationError(f"Failed to record audit event for design '{design_id}'.") from exc

    def query(
        self,
        *,
        design_id: Optional[str] = None,
        stakeholder: Optional[str] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Query audit events, optionally filtered by design, stakeholder, and/or date range.

        Args:
            design_id: Restrict to events for this design.
            stakeholder: Restrict to events attributed to this role/person.
            date_from: Only events recorded on/after this timestamp.
            date_to: Only events recorded on/before this timestamp.
            limit: Maximum number of events to return.

        Returns:
            Matching events, most recent first.

        Raises:
            FirestoreOperationError: On an unexpected Firestore failure.
        """
        try:
            query = self._collection
            if design_id:
                query = query.where("design_id", "==", design_id)
            if stakeholder:
                query = query.where("stakeholder", "==", stakeholder)
            if date_from:
                query = query.where("recorded_at", ">=", date_from)
            if date_to:
                query = query.where("recorded_at", "<=", date_to)
            query = query.order_by("recorded_at", direction=firestore.Query.DESCENDING).limit(limit)

            return [{"id": doc.id, **doc.to_dict()} for doc in query.stream()]
        except gcp_exceptions.GoogleAPICallError as exc:
            logger.exception("Failed to query audit trail")
            raise FirestoreOperationError("Failed to query the audit trail.") from exc


_audit_trail_service: Optional[AuditTrailService] = None


def get_audit_trail_service() -> AuditTrailService:
    """Return a process-wide singleton AuditTrailService (FastAPI dependency)."""
    global _audit_trail_service
    if _audit_trail_service is None:
        _audit_trail_service = AuditTrailService()
    return _audit_trail_service

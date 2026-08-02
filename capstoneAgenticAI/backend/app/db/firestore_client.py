"""Async Firestore data access for Design documents.

Wraps the google-cloud-firestore async client so route handlers never talk
to Firestore directly. All Firestore-level exceptions are translated into
``FirestoreOperationError`` (or a more specific ``AppError`` subclass like
``DesignNotFound``) so callers only need to handle application exceptions.
"""
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from google.api_core import exceptions as gcp_exceptions
from google.cloud import firestore

from app.config import Settings, get_settings
from app.db.models import Collection
from app.schemas.design import Design, DesignStatus
from app.utils.errors import DesignAlreadyExists, DesignNotFound, FirestoreOperationError
from app.utils.logger import get_logger

logger = get_logger(__name__)


class FirestoreClient:
    """Thin async data-access layer over the ``designs`` Firestore collection."""

    def __init__(self, settings: Optional[Settings] = None) -> None:
        """Initialize the underlying Firestore async client.

        Args:
            settings: Application settings; defaults to the cached global
                settings. Credentials are resolved via
                ``GOOGLE_APPLICATION_CREDENTIALS`` per standard GCP auth.
        """
        self._settings = settings or get_settings()
        self._client = firestore.AsyncClient(
            project=self._settings.GCP_PROJECT_ID,
            database=self._settings.FIRESTORE_DATABASE,
        )
        self._collection = self._client.collection(Collection.DESIGNS.value)

    async def create_design(self, design: Design) -> Design:
        """Persist a new design document.

        Args:
            design: The design to create. ``design.id`` is used as the
                Firestore document id.

        Returns:
            The created Design, unchanged.

        Raises:
            DesignAlreadyExists: If a document with this id already exists.
            FirestoreOperationError: On any other Firestore failure.
        """
        doc_ref = self._collection.document(design.id)
        try:
            existing = await doc_ref.get()
            if existing.exists:
                raise DesignAlreadyExists(design.id)

            data = design.model_dump(mode="json")
            data["deleted"] = False
            await doc_ref.set(data)
            logger.info("Created design %s", design.id)
            return design
        except DesignAlreadyExists:
            raise
        except gcp_exceptions.GoogleAPICallError as exc:
            logger.exception("Firestore error creating design %s", design.id)
            raise FirestoreOperationError(f"Failed to create design '{design.id}'.") from exc

    async def get_design(self, design_id: str) -> Design:
        """Fetch a single design by id.

        Args:
            design_id: The design's unique identifier.

        Returns:
            The matching Design.

        Raises:
            DesignNotFound: If no non-deleted document exists with this id.
            FirestoreOperationError: On any other Firestore failure.
        """
        doc_ref = self._collection.document(design_id)
        try:
            snapshot = await doc_ref.get()
        except gcp_exceptions.GoogleAPICallError as exc:
            logger.exception("Firestore error fetching design %s", design_id)
            raise FirestoreOperationError(f"Failed to fetch design '{design_id}'.") from exc

        if not snapshot.exists or snapshot.to_dict().get("deleted"):
            raise DesignNotFound(design_id)

        return Design.model_validate(snapshot.to_dict())

    async def list_designs(
        self, skip: int = 0, limit: int = 20, filters: Optional[Dict[str, Any]] = None
    ) -> List[Design]:
        """List designs with pagination and optional filters.

        Args:
            skip: Number of matching documents to skip.
            limit: Maximum number of documents to return.
            filters: Optional filters. Supported keys:
                - ``status``: exact-match a ``DesignStatus`` value.
                - ``date_from`` / ``date_to``: bound ``created_at`` (datetime).

        Returns:
            A list of matching, non-deleted Design objects ordered by
            ``created_at`` descending.

        Raises:
            FirestoreOperationError: On any Firestore failure.
        """
        filters = filters or {}
        try:
            query = self._collection.where("deleted", "==", False)

            status = filters.get("status")
            if status:
                query = query.where("status", "==", DesignStatus(status).value)

            date_from = filters.get("date_from")
            if isinstance(date_from, datetime):
                query = query.where("created_at", ">=", date_from)

            date_to = filters.get("date_to")
            if isinstance(date_to, datetime):
                query = query.where("created_at", "<=", date_to)

            query = query.order_by("created_at", direction=firestore.Query.DESCENDING)
            query = query.offset(skip).limit(limit)

            snapshots = query.stream()
            return [Design.model_validate(doc.to_dict()) async for doc in snapshots]
        except gcp_exceptions.GoogleAPICallError as exc:
            logger.exception("Firestore error listing designs")
            raise FirestoreOperationError("Failed to list designs.") from exc

    async def update_design(self, design_id: str, updates: Dict[str, Any]) -> Design:
        """Apply a partial update to a design.

        Args:
            design_id: The design's unique identifier.
            updates: Fields to merge into the existing document.
                ``updated_at`` is set automatically.

        Returns:
            The updated Design.

        Raises:
            DesignNotFound: If no non-deleted document exists with this id.
            FirestoreOperationError: On any other Firestore failure.
        """
        doc_ref = self._collection.document(design_id)
        try:
            snapshot = await doc_ref.get()
            if not snapshot.exists or snapshot.to_dict().get("deleted"):
                raise DesignNotFound(design_id)

            payload = dict(updates)
            payload["updated_at"] = datetime.now(timezone.utc)
            await doc_ref.update(payload)

            refreshed = await doc_ref.get()
            logger.info("Updated design %s", design_id)
            return Design.model_validate(refreshed.to_dict())
        except DesignNotFound:
            raise
        except gcp_exceptions.GoogleAPICallError as exc:
            logger.exception("Firestore error updating design %s", design_id)
            raise FirestoreOperationError(f"Failed to update design '{design_id}'.") from exc

    async def delete_design(self, design_id: str) -> None:
        """Soft-delete a design (marks it deleted, does not remove the document).

        Args:
            design_id: The design's unique identifier.

        Raises:
            DesignNotFound: If no non-deleted document exists with this id.
            FirestoreOperationError: On any other Firestore failure.
        """
        doc_ref = self._collection.document(design_id)
        try:
            snapshot = await doc_ref.get()
            if not snapshot.exists or snapshot.to_dict().get("deleted"):
                raise DesignNotFound(design_id)

            await doc_ref.update(
                {
                    "deleted": True,
                    "status": DesignStatus.DELETED.value,
                    "updated_at": datetime.now(timezone.utc),
                }
            )
            logger.info("Soft-deleted design %s", design_id)
        except DesignNotFound:
            raise
        except gcp_exceptions.GoogleAPICallError as exc:
            logger.exception("Firestore error deleting design %s", design_id)
            raise FirestoreOperationError(f"Failed to delete design '{design_id}'.") from exc


_firestore_client: Optional[FirestoreClient] = None


def get_firestore_client() -> FirestoreClient:
    """Return a process-wide singleton FirestoreClient (FastAPI dependency)."""
    global _firestore_client
    if _firestore_client is None:
        _firestore_client = FirestoreClient()
    return _firestore_client

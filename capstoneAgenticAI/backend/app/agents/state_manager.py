"""Persists Tree-of-Thought search state to Firestore for durability and resumption."""
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from google.api_core import exceptions as gcp_exceptions
from google.cloud import firestore

from app.config import Settings, get_settings
from app.db.models import Collection
from app.schemas.tot import ToTSearchState, TreeNodeState
from app.utils.errors import FirestoreOperationError
from app.utils.logger import get_logger

logger = get_logger(__name__)


class StateManager:
    """Manages and persists ToT beam-search state, keyed by ``design_id``.

    Keeps an in-memory mirror per ``design_id`` for fast reads within a
    single search, and flushes every mutation to Firestore immediately so a
    crashed process can resume via ``load_state``. The state shape
    (``ToTSearchState``) is a plain, JSON-serializable Pydantic model rather
    than a LangGraph checkpoint, so it can be persisted with the same
    Firestore access pattern used elsewhere in this codebase without coupling
    to LangGraph's (still-evolving) checkpointer interface.
    """

    def __init__(self, firestore_client: Optional[firestore.Client] = None, settings: Optional[Settings] = None) -> None:
        self._settings = settings or get_settings()
        self._client = firestore_client or firestore.Client(
            project=self._settings.GCP_PROJECT_ID, database=self._settings.FIRESTORE_DATABASE
        )
        self._collection = self._client.collection(Collection.TOT_SEARCH_STATE.value)
        self._cache: Dict[str, ToTSearchState] = {}

    def initialize_state(self, design_id: str, requirements: Dict[str, Any]) -> ToTSearchState:
        """Create (or reset) search state for a design and persist it.

        Args:
            design_id: Unique identifier for the design/search.
            requirements: Requirement data this search is based on (stored for
                context if the search needs to be resumed later).

        Returns:
            The freshly initialized state.
        """
        state = ToTSearchState(design_id=design_id, current_level=0, requirements_snapshot=requirements)
        self._cache[design_id] = state
        self._persist(state)
        logger.info("Initialized ToT search state for design '%s'", design_id)
        return state

    def save_node(self, design_id: str, node: TreeNodeState) -> ToTSearchState:
        """Append a node to the search history and persist the updated state.

        Args:
            design_id: The search this node belongs to.
            node: The tree node to record.

        Returns:
            The updated state.
        """
        state = self._require_state(design_id)
        state.all_nodes.append(node)
        state.current_level = max(state.current_level, node.level)
        self._persist(state)
        return state

    def load_state(self, design_id: str) -> Optional[ToTSearchState]:
        """Load persisted state for a design, from the in-memory cache or Firestore.

        Args:
            design_id: The search to load.

        Returns:
            The persisted state, or None if no search has been started for this id.

        Raises:
            FirestoreOperationError: On an unexpected Firestore failure.
        """
        if design_id in self._cache:
            return self._cache[design_id]

        try:
            snapshot = self._collection.document(design_id).get()
        except gcp_exceptions.GoogleAPICallError as exc:
            logger.exception("Failed to load ToT state for design '%s'", design_id)
            raise FirestoreOperationError(f"Failed to load ToT state for '{design_id}'.") from exc

        if not snapshot.exists:
            return None

        state = ToTSearchState.model_validate(snapshot.to_dict())
        self._cache[design_id] = state
        logger.info("Resumed ToT search state for design '%s' at level %d", design_id, state.current_level)
        return state

    def get_current_candidates(self, design_id: str) -> List[TreeNodeState]:
        """Return the current frontier of (non-pruned) candidate nodes for a search."""
        return self._require_state(design_id).candidates_at_level

    def update_best_paths(self, design_id: str, paths: List[TreeNodeState]) -> ToTSearchState:
        """Replace the current frontier and, once at the final layer, the best complete paths.

        Args:
            design_id: The search to update.
            paths: The new frontier of surviving nodes (the current beam).

        Returns:
            The updated state.
        """
        state = self._require_state(design_id)
        state.candidates_at_level = paths
        if state.current_level >= 4:
            state.best_complete_paths = paths
        self._persist(state)
        return state

    def _require_state(self, design_id: str) -> ToTSearchState:
        state = self._cache.get(design_id) or self.load_state(design_id)
        if state is None:
            raise FirestoreOperationError(
                f"No ToT search state found for design '{design_id}'; call initialize_state first."
            )
        return state

    def _persist(self, state: ToTSearchState) -> None:
        try:
            payload = state.model_dump(mode="json")
            payload["updated_at"] = datetime.now(timezone.utc)
            self._collection.document(state.design_id).set(payload)
        except gcp_exceptions.GoogleAPICallError as exc:
            logger.exception("Failed to persist ToT state for design '%s'", state.design_id)
            raise FirestoreOperationError(f"Failed to persist ToT state for '{state.design_id}'.") from exc


_state_manager: Optional[StateManager] = None


def get_state_manager() -> StateManager:
    """Return a process-wide singleton StateManager (FastAPI dependency)."""
    global _state_manager
    if _state_manager is None:
        _state_manager = StateManager()
    return _state_manager

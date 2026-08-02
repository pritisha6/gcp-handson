"""Lightweight in-memory TTL cache.

Used by the RAG system to avoid re-fetching pricing, compliance, and
precedent data on every request. A single-process, thread-safe dict is
enough for this deployment; if distributed caching is later needed,
swap the get/set calls for a Redis-backed implementation behind this
same two-method interface.
"""
import time
from dataclasses import dataclass
from threading import Lock
from typing import Any, Dict, Optional


@dataclass
class _CacheEntry:
    value: Any
    expires_at: float


class TTLCache:
    """Thread-safe in-memory cache with per-entry expiration."""

    def __init__(self) -> None:
        self._store: Dict[str, _CacheEntry] = {}
        self._lock = Lock()

    def get(self, key: str) -> Optional[Any]:
        """Return the cached value for ``key``, or None if missing/expired."""
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            if entry.expires_at < time.monotonic():
                del self._store[key]
                return None
            return entry.value

    def set(self, key: str, value: Any, ttl_seconds: float) -> None:
        """Store ``value`` under ``key`` for ``ttl_seconds`` before it expires."""
        with self._lock:
            self._store[key] = _CacheEntry(value=value, expires_at=time.monotonic() + ttl_seconds)

    def clear(self) -> None:
        """Remove all cached entries."""
        with self._lock:
            self._store.clear()

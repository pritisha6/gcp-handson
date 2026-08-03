"""Pinecone-backed vector store client for document chunk embeddings.

Handles both embedding generation (a local fastembed ONNX model) and vector
storage/retrieval (Pinecone). Chunking itself happens upstream in
``app.services.document_processor.DocumentProcessor``; this client only
embeds and persists/queries already-chunked text.
"""
from typing import Any, Dict, List, Optional

from fastembed import TextEmbedding
from pinecone import Pinecone, ServerlessSpec
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import Settings, get_settings
from app.utils.api_cost_tracker import api_cost_tracker
from app.utils.embedding_client import embed_texts, get_embedding_model
from app.utils.errors import ExternalServiceError
from app.utils.logger import get_logger

logger = get_logger(__name__)

_EMBED_BATCH_SIZE = 100
_METADATA_TEXT_LIMIT = 40_000  # Pinecone metadata value size limit is 40KB


class PineconeClient:
    """Wraps Pinecone (vector storage) and a local fastembed model (embeddings) for document RAG."""

    def __init__(self, settings: Optional[Settings] = None, embedding_model: Optional[TextEmbedding] = None) -> None:
        self._settings = settings or get_settings()
        self._pc = Pinecone(api_key=self._settings.PINECONE_API_KEY)
        self._embedding_model = embedding_model or get_embedding_model(self._settings)
        self._index_name: Optional[str] = None
        self._index = None

    def initialize_index(self, index_name: str) -> None:
        """Ensure a serverless Pinecone index exists and select it for use.

        Args:
            index_name: Name of the Pinecone index to create (if missing) and use.

        Raises:
            ExternalServiceError: If the index cannot be created or described.
        """
        try:
            existing = {info["name"] for info in self._pc.list_indexes()}
            if index_name not in existing:
                logger.info("Creating Pinecone index '%s'", index_name)
                self._pc.create_index(
                    name=index_name,
                    dimension=self._settings.EMBEDDING_DIMENSIONS,
                    metric="cosine",
                    spec=ServerlessSpec(
                        cloud=self._settings.PINECONE_CLOUD,
                        region=self._settings.PINECONE_REGION,
                    ),
                )
            self._index_name = index_name
            self._index = self._pc.Index(index_name)
        except Exception as exc:
            logger.exception("Failed to initialize Pinecone index '%s'", index_name)
            raise ExternalServiceError("pinecone", f"could not initialize index '{index_name}'") from exc

    def _ensure_index(self):
        if self._index is None:
            self.initialize_index(self._settings.PINECONE_INDEX_NAME)
        return self._index

    def _embed_batch(self, texts: List[str]) -> List[List[float]]:
        embeddings = embed_texts(self._embedding_model, texts)
        api_cost_tracker.record_call("local_embedding")
        return embeddings

    @retry(reraise=True, stop=stop_after_attempt(4), wait=wait_exponential(multiplier=1, min=1, max=20))
    def _upsert_batch(self, vectors: List[Dict[str, Any]], namespace: str) -> None:
        self._ensure_index().upsert(vectors=vectors, namespace=namespace)

    @retry(reraise=True, stop=stop_after_attempt(4), wait=wait_exponential(multiplier=1, min=1, max=20))
    def _query(self, embedding: List[float], top_k: int, namespace: str):
        return self._ensure_index().query(
            vector=embedding, top_k=top_k, namespace=namespace, include_metadata=True
        )

    def upsert_documents(self, chunks: List[Dict[str, Any]], namespace: str = "documents") -> List[str]:
        """Embed and upsert document chunks into Pinecone.

        Args:
            chunks: Chunk dicts with at least ``chunk_id`` and ``text``, plus
                arbitrary metadata fields (``document_id``, ``filename``, etc).
            namespace: Pinecone namespace to write into.

        Returns:
            The list of chunk ids that were upserted.

        Raises:
            ExternalServiceError: If embedding or upserting fails after retries.
        """
        if not chunks:
            return []

        upserted_ids: List[str] = []
        try:
            for start in range(0, len(chunks), _EMBED_BATCH_SIZE):
                batch = chunks[start : start + _EMBED_BATCH_SIZE]
                embeddings = self._embed_batch([chunk["text"] for chunk in batch])
                vectors = [
                    {
                        "id": chunk["chunk_id"],
                        "values": embedding,
                        "metadata": {
                            "text": chunk["text"][:_METADATA_TEXT_LIMIT],
                            **{k: v for k, v in chunk.items() if k not in ("chunk_id", "text")},
                        },
                    }
                    for chunk, embedding in zip(batch, embeddings)
                ]
                self._upsert_batch(vectors, namespace)
                upserted_ids.extend(v["id"] for v in vectors)

            logger.info("Upserted %d chunks to Pinecone namespace '%s'", len(upserted_ids), namespace)
            return upserted_ids
        except Exception as exc:
            logger.exception("Failed to upsert %d chunks to Pinecone", len(chunks))
            raise ExternalServiceError("pinecone", "failed to upsert document chunks") from exc

    def query_documents(
        self, query: str, top_k: int = 5, namespace: str = "documents"
    ) -> List[Dict[str, Any]]:
        """Return the top_k most relevant chunks for a query.

        Args:
            query: Natural-language query text.
            top_k: Number of results to return.
            namespace: Pinecone namespace to search.

        Returns:
            A list of dicts with ``id``, ``score``, ``text``, and ``metadata``.

        Raises:
            ExternalServiceError: If embedding or querying fails after retries.
        """
        try:
            [embedding] = self._embed_batch([query])
            result = self._query(embedding, top_k, namespace)
            matches = []
            for match in result.matches:
                metadata = dict(match.metadata or {})
                text = metadata.pop("text", "")
                matches.append({"id": match.id, "score": match.score, "text": text, "metadata": metadata})
            return matches
        except Exception as exc:
            logger.exception("Failed to query Pinecone namespace '%s'", namespace)
            raise ExternalServiceError("pinecone", "failed to query documents") from exc


_pinecone_client: Optional[PineconeClient] = None


def get_pinecone_client() -> PineconeClient:
    """Return a process-wide singleton PineconeClient (FastAPI dependency)."""
    global _pinecone_client
    if _pinecone_client is None:
        _pinecone_client = PineconeClient()
    return _pinecone_client

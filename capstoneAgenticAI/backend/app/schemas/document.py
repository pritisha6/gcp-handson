"""Schemas for document processing and chunking."""
from typing import Any, Dict, List

from pydantic import BaseModel, Field


class DocumentChunk(BaseModel):
    """A single chunk of extracted document text, ready for embedding."""

    chunk_id: str = Field(..., description="Unique identifier for this chunk (used as the Pinecone vector id)")
    document_id: str = Field(..., description="Identifier of the parent document")
    filename: str = Field(..., description="Original uploaded filename")
    source_type: str = Field(..., description="Detected file type, e.g. 'pdf', 'pptx', 'xlsx', 'html', 'txt', 'csv'")
    chunk_index: int = Field(..., ge=0, description="Position of this chunk within the document")
    text: str = Field(..., min_length=1, description="Chunk text content")
    token_count: int = Field(..., ge=0, description="Approximate token count of this chunk")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional context, e.g. page/slide/sheet")


class ProcessedDocument(BaseModel):
    """Result of processing a single uploaded file into chunks."""

    document_id: str = Field(..., description="Unique identifier for the processed document")
    filename: str = Field(..., description="Original uploaded filename")
    source_type: str = Field(..., description="Detected file type")
    total_chunks: int = Field(..., ge=0, description="Number of chunks produced")
    chunks: List[DocumentChunk] = Field(default_factory=list, description="Chunks with metadata")
    warnings: List[str] = Field(default_factory=list, description="Non-fatal issues encountered while processing")

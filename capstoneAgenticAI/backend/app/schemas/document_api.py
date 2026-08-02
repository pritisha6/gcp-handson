"""Request and response models for the document processing API."""
from typing import List

from pydantic import BaseModel, Field

from app.schemas.conflict import Conflict
from app.schemas.design import Requirement
from app.schemas.document import ProcessedDocument


class UploadDocumentsResponse(BaseModel):
    """Response for POST /api/documents/upload."""

    documents: List[ProcessedDocument] = Field(..., description="One entry per successfully processed file")


class ExtractRequirementsRequest(BaseModel):
    """Request body for POST /api/documents/extract."""

    documents: List[str] = Field(
        ..., min_length=1, description="Raw text segments (e.g. chunk texts) to extract requirements from"
    )


class ExtractRequirementsResponse(BaseModel):
    """Response for POST /api/documents/extract."""

    requirements: Requirement = Field(..., description="Structured requirements extracted from the documents")
    conflicts: List[Conflict] = Field(default_factory=list, description="Detected contradictions, if any")
    warnings: List[str] = Field(default_factory=list, description="Fields that were missing or ambiguous")

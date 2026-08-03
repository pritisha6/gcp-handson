"""Endpoints for uploading source documents and extracting requirements from them."""
import os
import tempfile
from pathlib import Path
from typing import List

from fastapi import APIRouter, Depends, File, UploadFile, status
from starlette.concurrency import run_in_threadpool

from app.config import Settings, get_settings
from app.schemas.document import ProcessedDocument
from app.schemas.document_api import (
    ExtractRequirementsRequest,
    ExtractRequirementsResponse,
    UploadDocumentsResponse,
)
from app.services.conflict_resolver import ConflictResolver, get_conflict_resolver
from app.services.document_processor import DocumentProcessor, get_document_processor
from app.services.requirement_extractor import RequirementExtractor, get_requirement_extractor
from app.utils.errors import FileTooLargeError
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/documents", tags=["documents"])

_UPLOAD_CHUNK_SIZE = 1024 * 1024  # 1MB, streamed to disk to avoid buffering huge files in memory


async def _save_upload_to_temp(upload: UploadFile, max_bytes: int) -> str:
    """Stream an UploadFile to a temp file, aborting early if it exceeds ``max_bytes``."""
    suffix = Path(upload.filename or "upload").suffix
    fd, tmp_path = tempfile.mkstemp(suffix=suffix)
    total = 0
    try:
        with os.fdopen(fd, "wb") as out:
            while True:
                chunk = await upload.read(_UPLOAD_CHUNK_SIZE)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise FileTooLargeError(upload.filename or "upload", total, max_bytes)
                out.write(chunk)
        return tmp_path
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise
    finally:
        await upload.close()


@router.post(
    "/upload",
    response_model=UploadDocumentsResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload, parse, chunk, and index one or more documents",
)
async def upload_documents(
    files: List[UploadFile] = File(..., description="PDF, PPTX, XLSX, HTML, TXT, or CSV files"),
    processor: DocumentProcessor = Depends(get_document_processor),
    settings: Settings = Depends(get_settings),
) -> UploadDocumentsResponse:
    """Save each upload to a temp file, parse/chunk it, index it in Pinecone, then clean up.

    Each file is validated and processed independently; a failure on one
    file does not stop the others.
    """
    max_bytes = settings.MAX_UPLOAD_FILE_SIZE_MB * 1024 * 1024
    processed: List[ProcessedDocument] = []

    for upload in files:
        tmp_path = await _save_upload_to_temp(upload, max_bytes)
        try:
            result = await run_in_threadpool(processor.process_file, tmp_path)
            processed.append(ProcessedDocument.model_validate(result))
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    logger.info("Processed %d uploaded document(s)", len(processed))
    return UploadDocumentsResponse(documents=processed)


@router.post(
    "/extract",
    response_model=ExtractRequirementsResponse,
    summary="Extract structured requirements and detect conflicts from document text",
)
async def extract_requirements(
    request: ExtractRequirementsRequest,
    extractor: RequirementExtractor = Depends(get_requirement_extractor),
    resolver: ConflictResolver = Depends(get_conflict_resolver),
) -> ExtractRequirementsResponse:
    """Run Groq-based requirement extraction, then rule-based conflict detection."""
    requirement, warnings = await run_in_threadpool(
        extractor.extract_requirements_with_warnings, request.documents
    )
    conflicts = await run_in_threadpool(resolver.detect_conflicts, requirement)

    return ExtractRequirementsResponse(requirements=requirement, conflicts=conflicts, warnings=warnings)

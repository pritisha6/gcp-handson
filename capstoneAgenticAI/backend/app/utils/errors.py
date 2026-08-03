"""Custom application exceptions and their FastAPI exception handlers."""
from typing import Any, Dict, Optional

from fastapi import Request, status
from fastapi.responses import JSONResponse


class AppError(Exception):
    """Base class for all application-raised errors.

    Carries an HTTP status code and machine-readable error code so a
    single exception handler can translate any subclass into a
    consistent JSON error response.
    """

    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    error_code: str = "internal_error"

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        self.message = message
        self.details = details or {}
        super().__init__(message)


class DesignNotFound(AppError):
    """Raised when a requested design does not exist."""

    status_code = status.HTTP_404_NOT_FOUND
    error_code = "design_not_found"

    def __init__(self, design_id: str) -> None:
        super().__init__(f"Design '{design_id}' was not found.", {"design_id": design_id})


class DesignAlreadyExists(AppError):
    """Raised when attempting to create a design that already exists."""

    status_code = status.HTTP_409_CONFLICT
    error_code = "design_already_exists"

    def __init__(self, design_id: str) -> None:
        super().__init__(f"Design '{design_id}' already exists.", {"design_id": design_id})


class RequirementValidationError(AppError):
    """Raised when a submitted requirement fails domain validation rules."""

    status_code = status.HTTP_400_BAD_REQUEST
    error_code = "requirement_validation_error"

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message, details)


class ComplianceError(AppError):
    """Raised when a design or requirement violates a compliance rule."""

    status_code = status.HTTP_400_BAD_REQUEST
    error_code = "compliance_error"

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message, details)


class FirestoreOperationError(AppError):
    """Raised when a Firestore read/write operation fails unexpectedly."""

    status_code = status.HTTP_502_BAD_GATEWAY
    error_code = "firestore_operation_error"

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message, details)


class UnsupportedFileTypeError(AppError):
    """Raised when an uploaded document's file type is not supported."""

    status_code = status.HTTP_400_BAD_REQUEST
    error_code = "unsupported_file_type"

    def __init__(self, filename: str, extension: str) -> None:
        super().__init__(
            f"Unsupported file type '{extension}' for '{filename}'.",
            {"filename": filename, "extension": extension},
        )


class FileTooLargeError(AppError):
    """Raised when an uploaded file exceeds the configured size limit."""

    status_code = status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
    error_code = "file_too_large"

    def __init__(self, filename: str, size_bytes: int, max_bytes: int) -> None:
        super().__init__(
            f"File '{filename}' ({size_bytes} bytes) exceeds the {max_bytes} byte limit.",
            {"filename": filename, "size_bytes": size_bytes, "max_bytes": max_bytes},
        )


class DocumentProcessingError(AppError):
    """Raised when a document cannot be parsed (corrupt, empty, or malformed)."""

    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    error_code = "document_processing_error"

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message, details)


class ExtractionError(AppError):
    """Raised when requirement extraction from documents fails irrecoverably."""

    status_code = status.HTTP_502_BAD_GATEWAY
    error_code = "extraction_error"

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message, details)


class ExternalServiceError(AppError):
    """Raised when a downstream service (Groq, OpenAI, Pinecone, GCP APIs) fails."""

    status_code = status.HTTP_502_BAD_GATEWAY
    error_code = "external_service_error"

    def __init__(self, service: str, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        details = {**(details or {}), "service": service}
        super().__init__(f"{service} error: {message}", details)


class NoFeasibleArchitectureError(AppError):
    """Raised when Tree-of-Thought search prunes every candidate branch before completion."""

    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    error_code = "no_feasible_architecture"

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message, details)


def _error_body(request: Request, error_code: str, message: str, details: Dict[str, Any]) -> Dict[str, Any]:
    correlation_id = getattr(request.state, "correlation_id", None)
    return {
        "error": {
            "code": error_code,
            "message": message,
            "details": details,
        },
        "correlation_id": correlation_id,
    }


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    """Translate any AppError subclass into a consistent JSON response."""
    return JSONResponse(
        status_code=exc.status_code,
        content=_error_body(request, exc.error_code, exc.message, exc.details),
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Fallback handler for exceptions not caught by more specific handlers."""
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=_error_body(request, "internal_error", "An unexpected error occurred.", {}),
    )

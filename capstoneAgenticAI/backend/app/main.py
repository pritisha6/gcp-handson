"""FastAPI application entrypoint for the ETL Design Agent backend."""
import time
import uuid
from contextlib import asynccontextmanager

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.routes.designs import router as designs_router
from app.routes.documents import router as documents_router
from app.routes.metrics import logs_router, router as metrics_router
from app.routes.validation import router as validation_router
from app.utils.errors import AppError, app_error_handler, unhandled_exception_handler
from app.utils.log_forwarders import configure_log_forwarding
from app.utils.logger import configure_logging, correlation_id_var, get_logger

settings = get_settings()
configure_logging(log_level=settings.LOG_LEVEL, environment=settings.ENVIRONMENT, log_format=settings.effective_log_format)
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup/shutdown hooks."""
    logger.info(
        "Starting ETL Design Agent backend | environment=%s project=%s",
        settings.ENVIRONMENT,
        settings.GCP_PROJECT_ID,
    )
    log_forwarding_listener = configure_log_forwarding(settings)
    yield
    if log_forwarding_listener is not None:
        log_forwarding_listener.stop()
    logger.info("Shutting down ETL Design Agent backend")


app = FastAPI(
    title="ETL Design Agent",
    description="AI system that generates optimal Google Cloud Platform ETL architecture designs.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def logging_middleware(request: Request, call_next):
    """Attach a correlation id to each request and log its outcome/latency."""
    correlation_id = request.headers.get("X-Correlation-ID", str(uuid.uuid4()))
    request.state.correlation_id = correlation_id
    token = correlation_id_var.set(correlation_id)

    start_time = time.perf_counter()
    logger.info("Request started: %s %s", request.method, request.url.path)
    try:
        response = await call_next(request)
    except Exception:
        logger.exception("Unhandled exception while processing %s %s", request.method, request.url.path)
        raise
    finally:
        correlation_id_var.reset(token)

    duration_ms = (time.perf_counter() - start_time) * 1000
    logger.info(
        "Request finished: %s %s -> %s (%.2fms)",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
    )
    response.headers["X-Correlation-ID"] = correlation_id
    return response


app.add_exception_handler(AppError, app_error_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Return a consistent error envelope for Pydantic/request validation failures."""
    correlation_id = getattr(request.state, "correlation_id", None)
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": {
                "code": "validation_error",
                "message": "Request validation failed.",
                "details": {"errors": jsonable_encoder(exc.errors())},
            },
            "correlation_id": correlation_id,
        },
    )


@app.get("/health", tags=["health"], summary="Health check")
async def health_check() -> dict:
    """Liveness/readiness probe endpoint."""
    return {"status": "ok", "environment": settings.ENVIRONMENT}


app.include_router(designs_router)
app.include_router(documents_router)
app.include_router(validation_router)
app.include_router(metrics_router)
app.include_router(logs_router)

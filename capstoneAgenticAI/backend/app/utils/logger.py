"""Logging configuration.

Logs to the console in all environments (as JSON in production, as
human-readable text otherwise, unless overridden). In production, also
attaches a Google Cloud Logging handler so logs are queryable in Cloud
Logging. Correlation IDs are threaded through via a context variable so
every log line emitted during a request can be tied back to that request.

``app.services.logging_service.LoggingService`` builds on top of this
module: it doesn't configure its own handlers, it just emits records
carrying a ``structured`` (and, for Cloud Logging, ``json_fields``) extra
payload that this module's formatters and handlers know how to render.
"""
import json
import logging
import sys
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Optional

correlation_id_var: ContextVar[Optional[str]] = ContextVar("correlation_id", default=None)


class CorrelationIdFilter(logging.Filter):
    """Injects the current request's correlation id into log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = correlation_id_var.get() or "-"
        return True


class JsonFormatter(logging.Formatter):
    """Formats each record as one JSON line, with millisecond-precision timestamps.

    Uses the record's ``structured`` extra (set by ``LoggingService``) when
    present, so category/details/etc. are preserved verbatim; otherwise
    builds a minimal structured envelope around the plain log message, so
    every line this app emits -- not just ``LoggingService`` calls -- is
    valid, parseable JSON.
    """

    def format(self, record: logging.LogRecord) -> str:
        structured = getattr(record, "structured", None)
        if structured is not None:
            payload = dict(structured)
        else:
            payload = {
                "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(timespec="milliseconds"),
                "level": record.levelname,
                "logger": record.name,
                "correlation_id": getattr(record, "correlation_id", None),
                "message": record.getMessage(),
            }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(log_level: str = "INFO", environment: str = "development", log_format: Optional[str] = None) -> None:
    """Configure root logging handlers.

    Idempotent: safe to call multiple times (e.g. in tests) without
    duplicating handlers.

    Args:
        log_level: Standard logging level name, e.g. "INFO" or "DEBUG".
        environment: Deployment environment; when "production" a Cloud
            Logging handler is attached in addition to the console handler.
        log_format: "json" or "text"; defaults to "json" in production and
            "text" otherwise.
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Avoid duplicate handlers on repeated calls (e.g. reload, tests).
    root_logger.handlers.clear()

    effective_format = log_format or ("json" if environment == "production" else "text")
    formatter: logging.Formatter
    if effective_format == "json":
        formatter = JsonFormatter()
    else:
        formatter = logging.Formatter(
            fmt="%(asctime)s | %(levelname)s | %(name)s | [%(correlation_id)s] | %(message)s"
        )
    correlation_filter = CorrelationIdFilter()

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.addFilter(correlation_filter)
    root_logger.addHandler(console_handler)

    if environment == "production":
        try:
            import google.cloud.logging as cloud_logging

            client = cloud_logging.Client()
            cloud_handler = client.get_default_handler()
            cloud_handler.addFilter(correlation_filter)
            root_logger.addHandler(cloud_handler)
        except Exception:
            logging.getLogger(__name__).warning(
                "Cloud Logging handler could not be initialized; falling back to console logging only.",
                exc_info=True,
            )


def get_logger(name: str) -> logging.Logger:
    """Return a module-level logger.

    Args:
        name: Typically ``__name__`` of the calling module.

    Returns:
        A standard library Logger configured by ``configure_logging``.
    """
    return logging.getLogger(name)

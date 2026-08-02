"""Optional HTTP log forwarders for third-party observability platforms.

Both integrations are strictly additive and opt-in: if the relevant
environment variables aren't set, ``configure_log_forwarding`` does
nothing. Real network calls run on a background thread via
``QueueHandler``/``QueueListener`` so a slow or unreachable endpoint never
blocks request handling, and a failed delivery is swallowed rather than
raised (a broken log sink must never break the app).
"""
import atexit
import json
import logging
from logging.handlers import QueueHandler, QueueListener
from queue import Queue
from typing import Optional

import httpx

from app.config import Settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


class _DatadogHandler(logging.Handler):
    """Forwards log records to the Datadog Logs intake API."""

    def __init__(self, api_key: str, site: str = "datadoghq.com", service: str = "etl-design-agent") -> None:
        super().__init__()
        self._url = f"https://http-intake.logs.{site}/api/v2/logs"
        self._api_key = api_key
        self._service = service
        self._client = httpx.Client(timeout=5.0)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            payload = getattr(record, "structured", None) or {"message": record.getMessage()}
            body = [
                {
                    "ddsource": "python",
                    "service": self._service,
                    "message": json.dumps(payload, default=str),
                }
            ]
            self._client.post(self._url, json=body, headers={"DD-API-KEY": self._api_key})
        except Exception:
            pass

    def close(self) -> None:
        self._client.close()
        super().close()


class _SplunkHecHandler(logging.Handler):
    """Forwards log records to a Splunk HTTP Event Collector (HEC) endpoint."""

    def __init__(self, hec_url: str, hec_token: str) -> None:
        super().__init__()
        self._url = hec_url.rstrip("/") + "/services/collector/event"
        self._token = hec_token
        self._client = httpx.Client(timeout=5.0)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            payload = getattr(record, "structured", None) or {"message": record.getMessage()}
            self._client.post(self._url, json={"event": payload}, headers={"Authorization": f"Splunk {self._token}"})
        except Exception:
            pass

    def close(self) -> None:
        self._client.close()
        super().close()


def configure_log_forwarding(settings: Settings) -> Optional[QueueListener]:
    """Attach Datadog/Splunk forwarders to the root logger, if configured.

    Args:
        settings: Application settings; reads ``DATADOG_API_KEY`` and/or
            ``SPLUNK_HEC_URL``/``SPLUNK_HEC_TOKEN``.

    Returns:
        The started ``QueueListener`` (callers should ``.stop()`` it on
        shutdown), or None if neither integration is configured.
    """
    sinks = []
    if settings.DATADOG_API_KEY:
        sinks.append(_DatadogHandler(settings.DATADOG_API_KEY, site=settings.DATADOG_SITE))
        logger.info("Datadog log forwarding enabled (site=%s)", settings.DATADOG_SITE)
    if settings.SPLUNK_HEC_URL and settings.SPLUNK_HEC_TOKEN:
        sinks.append(_SplunkHecHandler(settings.SPLUNK_HEC_URL, settings.SPLUNK_HEC_TOKEN))
        logger.info("Splunk HEC log forwarding enabled (url=%s)", settings.SPLUNK_HEC_URL)

    if not sinks:
        return None

    queue: "Queue[logging.LogRecord]" = Queue(-1)
    queue_handler = QueueHandler(queue)
    logging.getLogger().addHandler(queue_handler)

    listener = QueueListener(queue, *sinks, respect_handler_level=True)
    listener.start()
    atexit.register(listener.stop)
    return listener

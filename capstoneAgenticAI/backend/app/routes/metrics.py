"""Observability API: aggregate metrics, per-design metrics, trends, alerts, and recent logs."""
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from starlette.concurrency import run_in_threadpool

from app.schemas.logs import LogEntry
from app.schemas.metrics import Alert, DesignMetrics, MetricsSnapshot, TrendsResponse
from app.services.alert_service import AlertEvaluator, AlertNotifier, get_alert_evaluator, get_alert_notifier
from app.services.logging_service import LoggingService, get_logging_service
from app.services.metrics_service import MetricsService, get_metrics_service

router = APIRouter(prefix="/api/metrics", tags=["metrics"])
logs_router = APIRouter(prefix="/api", tags=["logs"])


@router.get("", response_model=MetricsSnapshot, summary="Overall metrics summary")
async def get_metrics(service: MetricsService = Depends(get_metrics_service)) -> MetricsSnapshot:
    """Aggregate quality/reliability/efficiency/user-impact metrics across all designs."""
    return await service.get_overall_metrics()


@router.get("/designs", response_model=List[DesignMetrics], summary="Per-design metrics")
async def list_design_metrics(
    limit: int = Query(default=100, ge=1, le=500),
    service: MetricsService = Depends(get_metrics_service),
) -> List[DesignMetrics]:
    """Stored per-design metrics, most recently created first."""
    return await run_in_threadpool(service.list_design_metrics, limit)


@router.get("/trends", response_model=TrendsResponse, summary="Trends over time")
async def get_trends(
    days: int = Query(default=30, ge=1, le=365, description="Size of the trend window, in days"),
    service: MetricsService = Depends(get_metrics_service),
) -> TrendsResponse:
    """Coverage, cost, and generation-time trends over the last ``days`` days."""
    return await service.get_trends(days)


@router.get("/alerts", response_model=List[Alert], summary="Current threshold-crossing alerts")
async def get_alerts(
    notify: bool = Query(default=False, description="If true, also dispatch configured Slack/email notifications"),
    metrics_service: MetricsService = Depends(get_metrics_service),
    evaluator: AlertEvaluator = Depends(get_alert_evaluator),
    notifier: AlertNotifier = Depends(get_alert_notifier),
) -> List[Alert]:
    """Evaluate current metrics against static thresholds.

    Safe to poll for a UI widget (``notify`` defaults to false, so normal
    dashboard polling never triggers Slack/email spam). Pass
    ``notify=true`` from a scheduled job to also dispatch notifications
    for whatever alerts are currently active.
    """
    snapshot = await metrics_service.get_overall_metrics()
    alerts = evaluator.evaluate(snapshot)
    if notify and alerts:
        await run_in_threadpool(notifier.notify, alerts)
    return alerts


@logs_router.get("/logs", response_model=List[LogEntry], summary="Recent structured logs")
async def get_logs(
    level: Optional[str] = Query(default=None, description="Minimum severity, e.g. 'WARNING'"),
    category: Optional[str] = Query(default=None, description="Restrict to one log category"),
    correlation_id: Optional[str] = Query(default=None, description="Restrict to one request/trace"),
    limit: int = Query(default=100, ge=1, le=1000),
    service: LoggingService = Depends(get_logging_service),
) -> List[LogEntry]:
    """Query recent logs from Cloud Logging, filtered by level/category/correlation id.

    Returns an empty list (not an error) if Cloud Logging isn't reachable
    in the current environment, e.g. local development without ADC.
    """
    return await run_in_threadpool(
        service.query_recent_logs, level=level, category=category, correlation_id=correlation_id, limit=limit
    )

"""Threshold-based alerting over aggregate metrics.

Thresholds are static Python configuration (deliberately not a
user-editable UI/database-backed ruleset — see ``AlertThresholds``), and
detection is a set of straightforward comparisons; no anomaly-detection
model is involved.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

import httpx

from app.config import Settings, get_settings
from app.schemas.metrics import Alert, AlertSeverity, MetricsSnapshot
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


@dataclass(frozen=True)
class AlertThresholds:
    """Static alert thresholds. Not user-configurable via the UI by design."""

    min_approval_rate_pct: float = 80.0
    max_hallucination_rate_pct: float = 5.0
    min_requirement_coverage_pct: float = 90.0
    min_consistency_pct: float = 50.0
    min_accuracy_pct: float = 70.0
    max_avg_generation_time_minutes: float = 20.0
    min_scalability_score: float = 50.0


class AlertEvaluator:
    """Compares a metrics snapshot against static thresholds and produces Alerts."""

    def __init__(self, thresholds: Optional[AlertThresholds] = None) -> None:
        self._thresholds = thresholds or AlertThresholds()

    def evaluate(self, metrics: MetricsSnapshot) -> List[Alert]:
        """Return every threshold crossed by the given metrics snapshot.

        Args:
            metrics: The aggregate metrics to check.

        Returns:
            Zero or more Alerts, most severe first.
        """
        now = _now_iso()
        t = self._thresholds
        alerts: List[Alert] = [
            *self._check_min("approval_rate_pct", metrics.reliability.approval_rate_pct, t.min_approval_rate_pct, now, "Approval rate"),
            *self._check_max("hallucination_rate_pct", metrics.reliability.hallucination_rate_pct, t.max_hallucination_rate_pct, now, "Hallucination rate"),
            *self._check_min("requirement_coverage_pct", metrics.quality.requirement_coverage_pct, t.min_requirement_coverage_pct, now, "Requirement coverage"),
            *self._check_min("consistency_pct", metrics.reliability.consistency_pct, t.min_consistency_pct, now, "Search consistency"),
            *self._check_min("accuracy_pct", metrics.quality.accuracy_pct, t.min_accuracy_pct, now, "Guardrail accuracy"),
            *self._check_max("avg_generation_time_minutes", metrics.efficiency.avg_generation_time_minutes, t.max_avg_generation_time_minutes, now, "Avg. generation time"),
            *self._check_min("scalability_score", metrics.quality.scalability_score, t.min_scalability_score, now, "Scalability score"),
        ]
        alerts.sort(key=lambda a: 0 if a.severity == AlertSeverity.CRITICAL else 1)
        return alerts

    def _check_min(self, metric: str, value: float, threshold: float, now: str, label: str) -> List[Alert]:
        if value >= threshold:
            return []
        severity = AlertSeverity.CRITICAL if value < threshold * 0.75 else AlertSeverity.WARNING
        return [
            Alert(
                metric=metric,
                severity=severity,
                threshold=threshold,
                current_value=value,
                message=f"{label} is {value:.1f}, below the {threshold:.1f} threshold.",
                triggered_at=now,
            )
        ]

    def _check_max(self, metric: str, value: float, threshold: float, now: str, label: str) -> List[Alert]:
        if value <= threshold:
            return []
        severity = AlertSeverity.CRITICAL if value > threshold * 1.5 else AlertSeverity.WARNING
        return [
            Alert(
                metric=metric,
                severity=severity,
                threshold=threshold,
                current_value=value,
                message=f"{label} is {value:.1f}, above the {threshold:.1f} threshold.",
                triggered_at=now,
            )
        ]


class AlertNotifier:
    """Sends alerts to Slack and/or email, if configured; both channels no-op silently otherwise."""

    def __init__(self, settings: Optional[Settings] = None, http_client: Optional[httpx.Client] = None) -> None:
        self._settings = settings or get_settings()
        self._http_client = http_client or httpx.Client(timeout=5.0)

    def notify(self, alerts: List[Alert]) -> None:
        """Send the given alerts to every configured channel (UI display is handled by the API layer)."""
        if not alerts:
            return

        sent_anywhere = False
        if self._settings.SLACK_WEBHOOK_URL:
            self._send_slack(alerts)
            sent_anywhere = True
        if self._settings.SMTP_HOST and self._settings.alert_email_recipients:
            self._send_email(alerts)
            sent_anywhere = True

        if not sent_anywhere:
            logger.info("%d alert(s) triggered; no Slack/email channel configured (UI-only).", len(alerts))

    def _send_slack(self, alerts: List[Alert]) -> None:
        lines = [f"*[{a.severity.value}]* {a.message}" for a in alerts]
        text = "ETL Design Agent alerts:\n" + "\n".join(lines)
        try:
            self._http_client.post(self._settings.SLACK_WEBHOOK_URL, json={"text": text})
        except Exception:
            logger.exception("Failed to send Slack alert notification")

    def _send_email(self, alerts: List[Alert]) -> None:
        import smtplib
        from email.mime.text import MIMEText

        body = "\n".join(f"[{a.severity.value}] {a.message}" for a in alerts)
        message = MIMEText(body)
        message["Subject"] = f"ETL Design Agent: {len(alerts)} alert(s) triggered"
        message["From"] = self._settings.ALERT_EMAIL_FROM or "noreply@etl-design-agent.local"
        message["To"] = ", ".join(self._settings.alert_email_recipients)

        try:
            with smtplib.SMTP(self._settings.SMTP_HOST, self._settings.SMTP_PORT, timeout=5) as server:
                server.starttls()
                if self._settings.SMTP_USERNAME and self._settings.SMTP_PASSWORD:
                    server.login(self._settings.SMTP_USERNAME, self._settings.SMTP_PASSWORD)
                server.send_message(message)
        except Exception:
            logger.exception("Failed to send alert email")


_alert_evaluator: Optional[AlertEvaluator] = None
_alert_notifier: Optional[AlertNotifier] = None


def get_alert_evaluator() -> AlertEvaluator:
    """Return a process-wide singleton AlertEvaluator (FastAPI dependency)."""
    global _alert_evaluator
    if _alert_evaluator is None:
        _alert_evaluator = AlertEvaluator()
    return _alert_evaluator


def get_alert_notifier() -> AlertNotifier:
    """Return a process-wide singleton AlertNotifier (FastAPI dependency)."""
    global _alert_notifier
    if _alert_notifier is None:
        _alert_notifier = AlertNotifier()
    return _alert_notifier

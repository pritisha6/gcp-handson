"""Estimates monthly GCP costs for ingestion, processing, and storage components.

Pricing figures come from ``RAGSystem.get_gcp_pricing`` (live GCP Billing
Catalog data when available, cached for 24h, with a static fallback), so
this module focuses purely on the usage-to-cost formulas per service.
"""
from typing import Any, Dict, Optional

from app.config import Settings, get_settings
from app.services.rag_system import RAGSystem, get_rag_system
from app.utils.logger import get_logger

logger = get_logger(__name__)

_SECONDS_PER_MONTH = 30 * 24 * 60 * 60


class CostCalculator:
    """Estimates monthly GCP costs for a proposed architecture."""

    def __init__(self, rag_system: Optional[RAGSystem] = None, settings: Optional[Settings] = None) -> None:
        self._settings = settings or get_settings()
        self._rag_system = rag_system or get_rag_system()

    def estimate_service_cost(self, service: str, requirements: Dict[str, Any]) -> float:
        """Estimate the monthly cost of a single GCP service.

        Args:
            service: One of 'pubsub', 'dataflow', 'bigquery_storage',
                'bigquery_query', 'cloud_storage', 'cloud_functions', 'firestore'.
            requirements: Usage parameters relevant to that service (e.g.
                throughput, storage size, invocation counts).

        Returns:
            Estimated monthly cost in USD (0.0 if the service is unrecognized).
        """
        handler = self._SERVICE_ESTIMATORS.get(service)
        if handler is None:
            logger.warning("No cost estimator for service '%s'; returning 0.0.", service)
            return 0.0
        pricing = self._rag_system.get_gcp_pricing(service, requirements)
        return handler(self, requirements, pricing)

    # --- Per-service estimators ---

    def _estimate_pubsub(self, req: Dict[str, Any], pricing: Dict[str, Any]) -> float:
        throughput_msgs_sec = req.get("throughput_msgs_sec", 0.0)
        avg_message_size_kb = req.get("avg_message_size_kb", 1.0)
        monthly_gib = (throughput_msgs_sec * avg_message_size_kb * _SECONDS_PER_MONTH) / (1024 * 1024)
        # Approximate publish + delivery as 2x the raw ingestion volume.
        return monthly_gib * 2 * pricing.get("unit_price_usd", 0.0)

    def _estimate_dataflow(self, req: Dict[str, Any], pricing: Dict[str, Any]) -> float:
        worker_count = req.get("worker_count", 1)
        vcpus_per_worker = req.get("vcpus_per_worker", 2)
        hours_per_month = req.get("hours_per_month", 730)  # default: always-on streaming job
        vcpu_hours = worker_count * vcpus_per_worker * hours_per_month
        return vcpu_hours * pricing.get("unit_price_usd", 0.0)

    def _estimate_bigquery_storage(self, req: Dict[str, Any], pricing: Dict[str, Any]) -> float:
        size_gb = req.get("size_gb", 0.0)
        return size_gb * pricing.get("unit_price_usd", 0.0)

    def _estimate_bigquery_query(self, req: Dict[str, Any], pricing: Dict[str, Any]) -> float:
        scanned_tb_per_month = req.get("scanned_tb_per_month", 0.0)
        return scanned_tb_per_month * pricing.get("unit_price_usd", 0.0)

    def _estimate_cloud_storage(self, req: Dict[str, Any], pricing: Dict[str, Any]) -> float:
        size_gb = req.get("size_gb", 0.0)
        return size_gb * pricing.get("unit_price_usd", 0.0)

    def _estimate_cloud_functions(self, req: Dict[str, Any], pricing: Dict[str, Any]) -> float:
        invocations_per_month = req.get("invocations_per_month", 0.0)
        avg_duration_sec = req.get("avg_duration_sec", 0.5)
        memory_gb = req.get("memory_gb", 0.25)
        gb_seconds = invocations_per_month * avg_duration_sec * memory_gb
        return gb_seconds * pricing.get("unit_price_usd", 0.0)

    def _estimate_firestore(self, req: Dict[str, Any], pricing: Dict[str, Any]) -> float:
        reads_per_month = req.get("reads_per_month", 0.0)
        return (reads_per_month / 100_000) * pricing.get("unit_price_usd", 0.0)

    _SERVICE_ESTIMATORS = {
        "pubsub": _estimate_pubsub,
        "dataflow": _estimate_dataflow,
        "bigquery_storage": _estimate_bigquery_storage,
        "bigquery_query": _estimate_bigquery_query,
        "cloud_storage": _estimate_cloud_storage,
        "cloud_functions": _estimate_cloud_functions,
        "firestore": _estimate_firestore,
    }

    def estimate_total_cost(self, architecture: Dict[str, Any]) -> Dict[str, Any]:
        """Estimate the total monthly cost of a proposed architecture.

        Args:
            architecture: Mapping of component name to
                ``{"service": str, "requirements": dict}``, e.g.
                ``{"ingestion": {"service": "pubsub", "requirements": {...}}}``.

        Returns:
            ``{"total_usd": float, "currency": "USD", "breakdown": {component: cost}}``.
        """
        breakdown: Dict[str, float] = {}
        for component, spec in architecture.items():
            service = spec.get("service")
            requirements = spec.get("requirements", {})
            if not service:
                logger.warning("Architecture component '%s' has no 'service'; skipping.", component)
                continue
            breakdown[component] = round(self.estimate_service_cost(service, requirements), 2)

        return {
            "total_usd": round(sum(breakdown.values()), 2),
            "currency": "USD",
            "breakdown": breakdown,
        }

    def compare_architectures(self, arch1: Dict[str, Any], arch2: Dict[str, Any]) -> Dict[str, Any]:
        """Compare the estimated monthly cost of two candidate architectures.

        Args:
            arch1: First architecture, shaped as ``estimate_total_cost`` expects.
            arch2: Second architecture, same shape.

        Returns:
            ``{"architecture_1": {...}, "architecture_2": {...},
            "difference_usd": float, "cheaper": "architecture_1" | "architecture_2" | "equal"}``.
        """
        cost1 = self.estimate_total_cost(arch1)
        cost2 = self.estimate_total_cost(arch2)
        difference = round(cost1["total_usd"] - cost2["total_usd"], 2)

        if difference > 0:
            cheaper = "architecture_2"
        elif difference < 0:
            cheaper = "architecture_1"
        else:
            cheaper = "equal"

        return {
            "architecture_1": cost1,
            "architecture_2": cost2,
            "difference_usd": abs(difference),
            "cheaper": cheaper,
        }

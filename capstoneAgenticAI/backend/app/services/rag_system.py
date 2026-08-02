"""Retrieval-Augmented Generation layer.

Four tiers of grounding data for design generation:
  1. Documents   - Pinecone (uploaded source documents)
  2. Pricing     - GCP Cloud Billing Catalog API, with a static fallback table
  3. Compliance  - Firestore ``compliance_rules`` collection
  4. Precedents  - Firestore ``design_precedents`` collection

All tiers are read-only and side-effect free from the caller's perspective,
so the interface is kept synchronous throughout (matching the other
services that consume it, e.g. ``CostCalculator``); Firestore access here
uses the synchronous client rather than the app's async client used for
design CRUD in the request path.
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from google.cloud import billing_v1
from google.cloud import firestore as firestore_module

from app.config import Settings, get_settings
from app.db.models import Collection
from app.db.pinecone_client import PineconeClient, get_pinecone_client
from app.schemas.rag import Document
from app.utils.cache import TTLCache
from app.utils.logger import get_logger

logger = get_logger(__name__)

_PRICING_TTL_SECONDS = 24 * 60 * 60
_COMPLIANCE_TTL_SECONDS = 60 * 60
_PRECEDENTS_TTL_SECONDS = 60 * 60

_SERVICE_DISPLAY_NAMES = {
    "pubsub": "Cloud Pub/Sub",
    "dataflow": "Cloud Dataflow",
    "bigquery_storage": "BigQuery",
    "bigquery_query": "BigQuery",
    "cloud_storage": "Cloud Storage",
    "cloud_functions": "Cloud Functions",
    "firestore": "Cloud Firestore",
}

# Approximate public on-demand GCP pricing (us-central1). Used only when the
# live Billing Catalog lookup is unavailable or finds no matching SKU.
_STATIC_PRICING_FALLBACK: Dict[str, Dict[str, Any]] = {
    "pubsub": {
        "unit": "GiB",
        "unit_price_usd": 0.04,
        "description": "Pub/Sub message ingestion/delivery (approx, per GiB)",
    },
    "dataflow": {
        "unit": "vCPU-hour",
        "unit_price_usd": 0.056,
        "description": "Dataflow batch worker vCPU-hour (approx)",
    },
    "bigquery_storage": {
        "unit": "GiB-month",
        "unit_price_usd": 0.02,
        "description": "BigQuery active storage (approx, per GiB/month)",
    },
    "bigquery_query": {
        "unit": "TiB",
        "unit_price_usd": 6.25,
        "description": "BigQuery on-demand query (approx, per TiB scanned)",
    },
    "cloud_storage": {
        "unit": "GiB-month",
        "unit_price_usd": 0.02,
        "description": "Cloud Storage Standard class (approx, per GiB/month)",
    },
    "cloud_functions": {
        "unit": "GB-second",
        "unit_price_usd": 0.0000025,
        "description": "Cloud Functions compute time (approx)",
    },
    "firestore": {
        "unit": "100k ops",
        "unit_price_usd": 0.06,
        "description": "Firestore document reads (approx, per 100k)",
    },
}


class RAGSystem(ABC):
    """Abstract retrieval layer over documents, pricing, compliance rules, and precedents."""

    @abstractmethod
    def retrieve_documents(self, query: str, top_k: int = 5) -> List[Document]:
        """Tier 1: retrieve the most relevant document chunks for a query."""

    @abstractmethod
    def get_gcp_pricing(self, service: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Tier 2: retrieve current (or best-known) GCP pricing for a service."""

    @abstractmethod
    def get_compliance_rules(self, regulation: str) -> Dict[str, Any]:
        """Tier 3: retrieve the compliance rule document for a regulation."""

    @abstractmethod
    def get_design_precedents(self, workload_type: str) -> List[Dict[str, Any]]:
        """Tier 4: retrieve prior design precedents for a workload type."""


class DefaultRAGSystem(RAGSystem):
    """Concrete RAG layer backed by Pinecone, the GCP Billing Catalog API, and Firestore."""

    def __init__(
        self,
        pinecone_client: Optional[PineconeClient] = None,
        settings: Optional[Settings] = None,
        cache: Optional[TTLCache] = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._pinecone_client = pinecone_client or get_pinecone_client()
        self._cache = cache or TTLCache()
        self._firestore = firestore_module.Client(
            project=self._settings.GCP_PROJECT_ID, database=self._settings.FIRESTORE_DATABASE
        )
        self._billing_client: Optional[billing_v1.CloudCatalogClient] = None

    # --- Tier 1: documents ---

    def retrieve_documents(self, query: str, top_k: int = 5) -> List[Document]:
        try:
            matches = self._pinecone_client.query_documents(query, top_k=top_k)
        except Exception:
            logger.warning("Document retrieval failed for query %r; returning no results.", query, exc_info=True)
            return []
        return [Document(id=m["id"], text=m["text"], score=m["score"], metadata=m["metadata"]) for m in matches]

    # --- Tier 2: pricing ---

    def get_gcp_pricing(self, service: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        cache_key = f"pricing:{service}:{sorted(parameters.items())}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        pricing = self._fetch_live_pricing(service, parameters) or self._fallback_pricing(service)
        self._cache.set(cache_key, pricing, _PRICING_TTL_SECONDS)
        return pricing

    def _fetch_live_pricing(self, service: str, parameters: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        try:
            if self._billing_client is None:
                self._billing_client = billing_v1.CloudCatalogClient()

            display_name = _SERVICE_DISPLAY_NAMES.get(service, service)
            matched_service = next(
                (
                    s
                    for s in self._billing_client.list_services()
                    if s.display_name.lower() == display_name.lower()
                ),
                None,
            )
            if matched_service is None:
                return None

            region = parameters.get("region")
            for sku in self._billing_client.list_skus(parent=matched_service.name):
                if region and sku.service_regions and region not in sku.service_regions:
                    continue
                if not sku.pricing_info:
                    continue
                pricing_expression = sku.pricing_info[0].pricing_expression
                tiers = pricing_expression.tiered_rates
                if not tiers:
                    continue
                rate = tiers[-1].unit_price
                return {
                    "service": service,
                    "sku": sku.description,
                    "unit": pricing_expression.usage_unit,
                    "unit_price_usd": rate.units + rate.nanos / 1e9,
                    "currency": rate.currency_code,
                    "source": "gcp_billing_api",
                }
            return None
        except Exception:
            logger.warning(
                "Live GCP pricing lookup failed for service '%s'; using fallback.", service, exc_info=True
            )
            return None

    def _fallback_pricing(self, service: str) -> Dict[str, Any]:
        fallback = _STATIC_PRICING_FALLBACK.get(service)
        if fallback is None:
            logger.warning("No pricing data (live or fallback) available for service '%s'.", service)
            return {"service": service, "unit": None, "unit_price_usd": 0.0, "currency": "USD", "source": "unknown"}
        return {"service": service, "currency": "USD", "source": "static_fallback", **fallback}

    # --- Tier 3: compliance rules ---

    def get_compliance_rules(self, regulation: str) -> Dict[str, Any]:
        cache_key = f"compliance:{regulation.lower()}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            docs = list(
                self._firestore.collection(Collection.COMPLIANCE_RULES.value)
                .where("regulation", "==", regulation)
                .limit(1)
                .stream()
            )
            result = docs[0].to_dict() if docs else {}
        except Exception:
            logger.warning(
                "Compliance rule lookup failed for '%s'; returning empty result.", regulation, exc_info=True
            )
            result = {}

        self._cache.set(cache_key, result, _COMPLIANCE_TTL_SECONDS)
        return result

    # --- Tier 4: design precedents ---

    def get_design_precedents(self, workload_type: str) -> List[Dict[str, Any]]:
        cache_key = f"precedents:{workload_type.lower()}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            results = [
                doc.to_dict()
                for doc in self._firestore.collection(Collection.DESIGN_PRECEDENTS.value)
                .where("workload_type", "==", workload_type)
                .limit(5)
                .stream()
            ]
        except Exception:
            logger.warning(
                "Design precedent lookup failed for '%s'; returning no precedents.", workload_type, exc_info=True
            )
            results = []

        self._cache.set(cache_key, results, _PRECEDENTS_TTL_SECONDS)
        return results


_rag_system: Optional[RAGSystem] = None


def get_rag_system() -> RAGSystem:
    """Return a process-wide singleton RAGSystem (FastAPI dependency)."""
    global _rag_system
    if _rag_system is None:
        _rag_system = DefaultRAGSystem()
    return _rag_system

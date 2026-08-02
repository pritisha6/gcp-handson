"""Shared static reference data about GCP (and common third-party) services.

Used by both ``CriticEvaluator`` (continuous scoring for Tree-of-Thought beam
search) and ``GuardrailValidator`` (discrete pass/fail safety gates) so the
two systems don't silently drift apart on what they believe about a given
service. All figures here are illustrative approximations for scoring
purposes, not authoritative GCP documentation.
"""
from typing import Dict, FrozenSet, Optional, Set

# Rough latency tier for well-known services.
LATENCY_TIER_BY_SERVICE: Dict[str, str] = {
    "pub/sub": "streaming",
    "pubsub": "streaming",
    "kafka": "streaming",
    "dataflow": "streaming",
    "cloud functions": "streaming",
    "cloud run": "streaming",
    "bigquery": "near-real-time",
    "dataproc": "batch",
    "cloud storage": "batch",
    "cloud composer": "batch",
    "airflow": "batch",
    "transfer service": "batch",
}

# Rough operational complexity for well-known services.
OPS_COMPLEXITY_BY_SERVICE: Dict[str, str] = {
    "kafka": "high",
    "dataproc": "high",
    "kubernetes": "high",
    "gke": "high",
    "airflow": "medium",
    "cloud composer": "medium",
    "dataflow": "medium",
    "pub/sub": "low",
    "pubsub": "low",
    "bigquery": "low",
    "cloud storage": "low",
    "cloud functions": "low",
    "cloud run": "low",
    "firestore": "low",
}

# Skill keywords considered relevant to operating a service of a given complexity tier.
RELEVANT_SKILL_KEYWORDS: Dict[str, Set[str]] = {
    "high": {"kafka", "dataproc", "kubernetes", "gke", "spark", "hadoop"},
    "medium": {"airflow", "dataflow", "beam", "composer", "python", "sql"},
}

# Illustrative rough training investment to close a skill gap, by complexity tier.
TRAINING_ESTIMATE_BY_COMPLEXITY: Dict[str, str] = {
    "high": "~4-6 weeks of training or hiring a specialist (~$15,000-$25,000)",
    "medium": "~1-2 weeks of training (~$3,000-$5,000)",
    "low": "minimal ramp-up expected",
}

# Known GCP service limits used for realism checks (illustrative, approximate).
GCP_LIMITS: Dict[str, float] = {
    "pubsub_max_msgs_sec_per_partition": 100_000,
    "pubsub_max_practical_msgs_sec_single_topic": 1_000_000,  # roughly, before needing to shard across topics
    "cloud_functions_max_timeout_sec_gen2": 3600,
    "firestore_max_doc_size_bytes": 1_048_576,
}

# Known-incompatible service pairings (illustrative, non-exhaustive). Each
# entry is a frozenset of lowercase substrings that should not co-occur
# across adjacent layers of one architecture path.
INCOMPATIBLE_PAIRS: Set[FrozenSet[str]] = {
    frozenset({"firestore", "dataproc"}),  # Firestore is not a Spark/Hadoop data source
}

TIGHT_FRESHNESS_VALUES: Set[str] = {"real-time", "realtime", "near-real-time"}
LOOSE_FRESHNESS_VALUES: Set[str] = {"daily", "batch", "hourly"}


def tier_for_service(table: Dict[str, str], service_name: str) -> Optional[str]:
    """Look up the first table entry whose key is a substring of ``service_name``."""
    name = service_name.lower()
    for key, tier in table.items():
        if key in name:
            return tier
    return None

"""Observability and metrics for cf-bypass-cli (v2.0).

Tracks every bypass attempt with structured metrics persisted to SQLite.
Provides CLI querying (cf-bypass stats) and an optional dashboard.

Key components:
- metrics: BypassMetrics data model
- storage: SQLite persistence with async writes
- dashboard: Optional FastAPI dashboard on configurable port
"""

from cf_bypass.observability.metrics import BypassMetrics, record_metrics
from cf_bypass.observability.storage import MetricsStorage

__all__ = [
    "BypassMetrics",
    "record_metrics",
    "MetricsStorage",
]

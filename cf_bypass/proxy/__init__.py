"""Proxy pool management with rotation, health checks, and provider adapters.

Replaces the single `ProxyConfig` URL with a full-featured pool:
- Multiple proxy nodes with metadata (geo, type, quality)
- Configurable rotation strategies (round_robin, random, weighted, least_used)
- Health monitoring with automatic cooldown
- Provider adapters for BrightData, Oxylabs, IPIDEA, local files
- Backward-compatible with old `proxy.url` config format
"""

from cf_bypass.proxy.pool import ProxyPool, ProxyNode
from cf_bypass.proxy.rotation import RotationStrategy, get_rotation_strategy
from cf_bypass.proxy.quality import QualityScorer
from cf_bypass.proxy.health import HealthChecker

__all__ = [
    "ProxyPool",
    "ProxyNode",
    "RotationStrategy",
    "get_rotation_strategy",
    "QualityScorer",
    "HealthChecker",
]

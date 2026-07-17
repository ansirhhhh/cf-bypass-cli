"""Proxy health checker.

Periodically validates proxy connectivity and GeoIP before use.
Reuses the existing ProxyChecker for latency/geo checks.
"""

import time
from typing import TYPE_CHECKING, Optional

from cf_bypass.logging_config import get_logger

if TYPE_CHECKING:
    from cf_bypass.proxy.pool import ProxyNode

logger = get_logger("proxy.health")


class HealthChecker:
    """Check proxy connectivity and GeoIP.

    Usage::

        checker = HealthChecker()
        is_healthy = await checker.check(proxy_node, timeout=10.0)
    """

    def __init__(self, check_geo: bool = True, geo_api: str = ""):
        """Initialize health checker.

        Args:
            check_geo: If True, also verify GeoIP match.
            geo_api: GeoIP service URL. Uses ip-api.com by default.
        """
        self.check_geo = check_geo
        self.geo_api = geo_api or "http://ip-api.com/json"

    async def check(
        self,
        proxy: "ProxyNode",
        timeout: float = 10.0,
    ) -> bool:
        """Check if a proxy is healthy.

        Verifies:
        1. TCP connectivity (via the existing ProxyChecker)
        2. Optional GeoIP verification

        Args:
            proxy: The proxy node to check.
            timeout: Maximum check time in seconds.

        Returns:
            True if the proxy is healthy.
        """
        try:
            from cf_bypass.proxy_checker import ProxyChecker

            # Use existing ProxyChecker for latency check
            result = await ProxyChecker.check_latency(
                proxy.url, timeout=timeout
            )

            if not result.healthy:
                logger.debug(
                    f"Proxy {proxy.url[:50]}... unhealthy: {result.error}"
                )
                return False

            # GeoIP verification
            if self.check_geo and proxy.geo_country:
                if not result.geo_match(proxy.geo_country):
                    logger.debug(
                        f"Proxy {proxy.url[:50]}... geo mismatch: "
                        f"expected {proxy.geo_country}, got {result.country}"
                    )
                    return False

            logger.debug(
                f"Proxy {proxy.url[:50]}... healthy "
                f"({result.latency_ms:.0f}ms, {result.country})"
            )
            return True

        except Exception as exc:
            logger.debug(f"Health check failed for {proxy.url[:50]}...: {exc}")
            return False

    async def check_all(
        self,
        proxies: list,
        timeout: float = 10.0,
    ) -> dict:
        """Check multiple proxies. Returns {url: healthy}."""
        results = {}
        for proxy in proxies:
            results[proxy.url] = await self.check(proxy, timeout=timeout)
        return results

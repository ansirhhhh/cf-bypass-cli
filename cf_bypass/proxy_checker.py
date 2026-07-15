"""Proxy health validation, geo-verification, and anonymity checking.

Provides lightweight async checks to validate a proxy before using it
in the bypass strategy chain.  Uses httpx (already a project dependency)
to make test requests through the proxy.
"""

import time
from dataclasses import dataclass
from typing import Optional

import httpx

from cf_bypass.logging_config import get_logger

logger = get_logger("proxy_checker")

# Default geo-IP endpoint — free, no API key required
DEFAULT_GEO_CHECK_URL = "http://ip-api.com/json"


@dataclass
class ProxyHealth:
    """Result of a proxy health / validation check."""

    healthy: bool
    latency_ms: float = 0.0
    ip: str = ""
    country: str = ""
    isp: str = ""
    error: Optional[str] = None

    def geo_match(self, required_geo: str) -> bool:
        """Return True when the detected country matches *required_geo*.

        Comparison is case-insensitive.  An empty *required_geo* always
        matches (no geo constraint).
        """
        if not required_geo:
            return True
        return self.country.upper() == required_geo.upper()


class ProxyChecker:
    """Validate proxy reachability, latency, and geo-location.

    Usage::

        checker = ProxyChecker()
        health = await checker.check_latency("http://proxy:8080")
        if health.healthy:
            print(f"Proxy OK: {health.ip} ({health.country})")
    """

    @staticmethod
    async def check_latency(
        proxy_url: str,
        timeout: float = 10.0,
        test_url: str = DEFAULT_GEO_CHECK_URL,
    ) -> ProxyHealth:
        """Measure proxy round-trip time and basic reachability.

        Makes a GET request to *test_url* through *proxy_url* and reports
        latency, IP, and country information.

        Returns:
            ProxyHealth with ``healthy=True`` if the proxy responds within
            *timeout* seconds and returns a valid JSON response.
        """
        start = time.time()
        try:
            async with httpx.AsyncClient(
                proxy=proxy_url,
                timeout=timeout,
            ) as client:
                response = await client.get(test_url)
                latency = (time.time() - start) * 1000

                if response.status_code != 200:
                    return ProxyHealth(
                        healthy=False,
                        latency_ms=round(latency, 1),
                        error=f"Health endpoint returned HTTP {response.status_code}",
                    )

                data = response.json()
                return ProxyHealth(
                    healthy=True,
                    latency_ms=round(latency, 1),
                    ip=data.get("query", ""),
                    country=data.get("countryCode", data.get("country", "")),
                    isp=data.get("isp", data.get("org", "")),
                )

        except httpx.ConnectError as exc:
            latency = (time.time() - start) * 1000
            logger.debug(f"Proxy connection failed: {exc}")
            return ProxyHealth(
                healthy=False,
                latency_ms=round(latency, 1),
                error=f"Connection refused or unreachable: {exc}",
            )
        except httpx.TimeoutException:
            latency = (time.time() - start) * 1000
            return ProxyHealth(
                healthy=False,
                latency_ms=round(latency, 1),
                error=f"Proxy timeout after {timeout}s",
            )
        except Exception as exc:
            latency = (time.time() - start) * 1000
            logger.debug(f"Proxy health check error: {exc}")
            return ProxyHealth(
                healthy=False,
                latency_ms=round(latency, 1),
                error=str(exc),
            )

    @staticmethod
    async def check_geo(
        proxy_url: str,
        expected_country: str = "",
        timeout: float = 10.0,
    ) -> ProxyHealth:
        """Validate that a proxy exits in the expected country.

        Args:
            proxy_url: Full proxy URL.
            expected_country: ISO 2-letter country code (e.g. ``"AU"``).
                An empty string skips the geo check and reports whatever
                country is detected.

        Returns:
            ProxyHealth.  ``healthy`` is False when the geo check is
            requested but the detected country does not match.
        """
        health = await ProxyChecker.check_latency(
            proxy_url, timeout=timeout
        )

        if not health.healthy:
            return health

        if expected_country and not health.geo_match(expected_country):
            health.healthy = False
            health.error = (
                f"Geo mismatch: expected {expected_country.upper()}, "
                f"got {health.country}"
            )
            logger.warning(health.error)

        return health

    @staticmethod
    async def full_check(
        proxy_url: str,
        geo_required: str = "",
        timeout: float = 10.0,
    ) -> ProxyHealth:
        """Run latency + geo verification in one call.

        This is the recommended entry point for pre-flight proxy validation.
        """
        return await ProxyChecker.check_geo(
            proxy_url,
            expected_country=geo_required,
            timeout=timeout,
        )

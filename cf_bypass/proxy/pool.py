"""Proxy pool with rotation, health monitoring, and geo filtering.

The ProxyPool is the central management layer for all proxy nodes.
It handles:
- Node selection with configurable rotation strategy
- Health tracking (success/failure counts)
- Automatic cooldown for failing proxies
- Geo-based filtering
- Backward compatibility with single-proxy config
"""

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Dict, List, Literal

from cf_bypass.proxy.rotation import RotationStrategy, get_rotation_strategy
from cf_bypass.proxy.quality import QualityScorer
from cf_bypass.proxy.health import HealthChecker
from cf_bypass.logging_config import get_logger

logger = get_logger("proxy.pool")


@dataclass
class ProxyNode:
    """A single proxy entry in the pool.

    Attributes:
        url: Full proxy URL (http://user:pass@host:port).
        protocol: "http", "https", or "socks5".
        provider: Provider name (e.g., "brightdata", "oxylabs", "file").
        geo_country: ISO 3166-1 alpha-2 country code.
        geo_city: Optional city name.
        proxy_type: "residential", "datacenter", "mobile", or "isp".
        quality_score: 0.0-1.0, higher is better.
        success_count: Total successful uses.
        failure_count: Total failed uses.
        last_used: When this proxy was last selected.
        last_health_check: When health was last verified.
        cooldown_until: If set, proxy is in cooldown until this time.
        cost_per_gb: Estimated cost in USD per GB (for cost-aware selection).
        sticky_session_id: Optional session ID for session-sticky proxies.
        tags: Arbitrary string tags for filtering.
    """

    url: str
    protocol: Literal["http", "https", "socks5"] = "http"
    provider: str = "manual"
    geo_country: str = ""
    geo_city: str = ""
    proxy_type: Literal["residential", "datacenter", "mobile", "isp"] = "datacenter"
    quality_score: float = 1.0
    success_count: int = 0
    failure_count: int = 0
    last_used: Optional[datetime] = None
    last_health_check: Optional[datetime] = None
    cooldown_until: Optional[datetime] = None
    cost_per_gb: float = 0.0
    sticky_session_id: Optional[str] = None
    tags: List[str] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        """Return success rate (0.0-1.0) over all recorded uses."""
        total = self.success_count + self.failure_count
        return self.success_count / total if total > 0 else 1.0

    @property
    def is_available(self) -> bool:
        """Return True if the proxy is not in cooldown."""
        if self.cooldown_until is None:
            return True
        return datetime.now(timezone.utc) >= self.cooldown_until

    @property
    def weight(self) -> float:
        """Composite weight for weighted selection.

        Combines quality score and success rate for a fair selection weight.
        """
        return (self.quality_score * 0.6 + self.success_rate * 0.4)

    def record_success(self, latency_ms: float = 0.0) -> None:
        """Record a successful use of this proxy."""
        self.success_count += 1
        self.last_used = datetime.now(timezone.utc)
        # Improve quality slightly on success
        self.quality_score = min(1.0, self.quality_score + 0.02)

    def record_failure(self, error: str = "") -> None:
        """Record a failed use of this proxy."""
        self.failure_count += 1
        self.last_used = datetime.now(timezone.utc)
        # Degrade quality on failure
        self.quality_score = max(0.0, self.quality_score - 0.05)

    def to_dict(self) -> dict:
        """Serialize to dict for storage/debugging."""
        return {
            "url": self.url,
            "protocol": self.protocol,
            "provider": self.provider,
            "geo_country": self.geo_country,
            "proxy_type": self.proxy_type,
            "quality_score": round(self.quality_score, 2),
            "success_rate": round(self.success_rate, 2),
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "is_available": self.is_available,
        }

    @classmethod
    def from_url(cls, url: str, **kwargs) -> "ProxyNode":
        """Create a ProxyNode from a simple URL string (backward compat)."""
        return cls(url=url, **kwargs)


class ProxyPool:
    """Manages a pool of proxy nodes with rotation and health monitoring.

    Usage::

        pool = ProxyPool([
            ProxyNode.from_url("http://user:pass@proxy1:8080", geo_country="US"),
            ProxyNode.from_url("http://user:pass@proxy2:8080", geo_country="DE"),
        ])

        # Get a proxy
        proxy = await pool.get(geo="US")
        # Use it...
        await pool.report_result(proxy, success=True, latency_ms=350.0)
    """

    def __init__(
        self,
        proxies: Optional[List[ProxyNode]] = None,
        strategy: Literal["round_robin", "random", "weighted", "least_used"] = "weighted",
        health_check_interval: int = 300,
        cooldown_after_failures: int = 3,
        cooldown_duration: int = 600,
        min_quality: float = 0.3,
    ):
        """Initialize the proxy pool.

        Args:
            proxies: Initial list of ProxyNode entries.
            strategy: Rotation strategy name.
            health_check_interval: Seconds between health checks.
            cooldown_after_failures: Consecutive failures before cooldown.
            cooldown_duration: Cooldown duration in seconds.
            min_quality: Minimum quality score to be eligible for selection.
        """
        self.proxies: List[ProxyNode] = proxies or []
        self.strategy_name = strategy
        self.strategy = get_rotation_strategy(strategy)
        self.health_check_interval = health_check_interval
        self.cooldown_after_failures = cooldown_after_failures
        self.cooldown_duration = cooldown_duration
        self.min_quality = min_quality

        self._round_robin_index = 0
        self._quality_scorer = QualityScorer()
        self._health_checker = HealthChecker()

    # ------------------------------------------------------------------
    # Proxy selection
    # ------------------------------------------------------------------

    async def get(
        self,
        geo: str = "",
        min_quality: Optional[float] = None,
        proxy_type: Optional[str] = None,
        exclude_urls: Optional[List[str]] = None,
    ) -> Optional[ProxyNode]:
        """Select the best available proxy matching constraints.

        Args:
            geo: ISO country code filter (e.g., "US"). Empty = no filter.
            min_quality: Minimum quality score override.
            proxy_type: Filter by type ("residential", "datacenter", etc.).
            exclude_urls: URLs to exclude from selection.

        Returns:
            A ProxyNode, or None if no eligible proxy is available.
        """
        min_q = min_quality if min_quality is not None else self.min_quality
        exclude = set(exclude_urls or [])

        # Filter candidates
        candidates = [
            p for p in self.proxies
            if p.is_available
            and p.quality_score >= min_q
            and p.url not in exclude
        ]

        if geo:
            candidates = [p for p in candidates if p.geo_country.upper() == geo.upper()]

        if proxy_type:
            candidates = [p for p in candidates if p.proxy_type == proxy_type]

        if not candidates:
            logger.warning(
                f"No eligible proxy (geo={geo or 'any'}, "
                f"min_quality={min_q}, type={proxy_type or 'any'})"
            )
            return None

        # Select using the configured strategy
        proxy = self.strategy.select(candidates, pool=self)
        if proxy:
            proxy.last_used = datetime.now(timezone.utc)

        return proxy

    async def get_many(
        self,
        count: int,
        geo: str = "",
        **kwargs,
    ) -> List[ProxyNode]:
        """Select multiple proxies (without duplicates)."""
        results = []
        exclude = []
        for _ in range(count):
            proxy = await self.get(geo=geo, exclude_urls=exclude, **kwargs)
            if proxy:
                results.append(proxy)
                exclude.append(proxy.url)
            else:
                break
        return results

    # ------------------------------------------------------------------
    # Result reporting
    # ------------------------------------------------------------------

    async def report_result(
        self,
        proxy: ProxyNode,
        success: bool,
        latency_ms: float = 0.0,
        error: str = "",
    ) -> None:
        """Report the result of using a proxy.

        Updates the proxy's stats and triggers cooldown if needed.

        Args:
            proxy: The ProxyNode that was used.
            success: Whether the request succeeded.
            latency_ms: Response latency in ms.
            error: Error message on failure.
        """
        if success:
            proxy.record_success(latency_ms)
            logger.debug(
                f"Proxy {proxy.url[:40]}... success ({latency_ms:.0f}ms)"
            )
        else:
            proxy.record_failure(error)
            logger.debug(
                f"Proxy {proxy.url[:40]}... failure: {error[:80]}"
            )

        # Update quality score
        proxy.quality_score = self._quality_scorer.evaluate(proxy)

    def trigger_cooldown(self, proxy: ProxyNode) -> None:
        """Manually put a proxy in cooldown."""
        cooldown_until = datetime.now(timezone.utc)
        # Use timedelta via timestamp math to avoid import issues
        from datetime import timedelta
        proxy.cooldown_until = cooldown_until + timedelta(
            seconds=self.cooldown_duration
        )
        logger.info(
            f"Proxy {proxy.url[:40]}... in cooldown for "
            f"{self.cooldown_duration}s"
        )

    # ------------------------------------------------------------------
    # Pool management
    # ------------------------------------------------------------------

    def add_proxy(self, proxy: ProxyNode) -> None:
        """Add a proxy to the pool."""
        self.proxies.append(proxy)
        logger.debug(f"Added proxy: {proxy.url[:50]}... ({proxy.geo_country})")

    def remove_proxy(self, url: str) -> bool:
        """Remove a proxy by URL. Returns True if removed."""
        for i, p in enumerate(self.proxies):
            if p.url == url:
                self.proxies.pop(i)
                logger.debug(f"Removed proxy: {url[:50]}...")
                return True
        return False

    def add_proxies_from_urls(
        self,
        urls: List[str],
        provider: str = "manual",
        geo_country: str = "",
        proxy_type: str = "datacenter",
    ) -> int:
        """Bulk-add proxies from URL strings. Returns count added."""
        added = 0
        for url in urls:
            if url.strip():
                self.add_proxy(ProxyNode(
                    url=url.strip(),
                    provider=provider,
                    geo_country=geo_country,
                    proxy_type=proxy_type,
                ))
                added += 1
        return added

    async def health_check_all(self) -> Dict[str, bool]:
        """Run health checks on all proxies. Returns {url: healthy}."""
        results = {}
        for proxy in self.proxies:
            healthy = await self._health_checker.check(proxy, timeout=10.0)
            results[proxy.url] = healthy
            proxy.last_health_check = datetime.now(timezone.utc)

            if not healthy:
                self.trigger_cooldown(proxy)

        healthy_count = sum(1 for v in results.values() if v)
        logger.info(
            f"Proxy health check: {healthy_count}/{len(results)} healthy"
        )
        return results

    def stats(self) -> dict:
        """Return pool statistics for monitoring."""
        available = [p for p in self.proxies if p.is_available]
        return {
            "total": len(self.proxies),
            "available": len(available),
            "in_cooldown": len(self.proxies) - len(available),
            "avg_quality": (
                sum(p.quality_score for p in self.proxies) / len(self.proxies)
                if self.proxies else 0
            ),
            "avg_success_rate": (
                sum(p.success_rate for p in self.proxies) / len(self.proxies)
                if self.proxies else 0
            ),
            "by_type": self._count_by("proxy_type"),
            "by_country": self._count_by("geo_country"),
            "strategy": self.strategy_name,
        }

    def _count_by(self, attr: str) -> dict:
        """Count proxies grouped by an attribute."""
        counts: Dict[str, int] = {}
        for p in self.proxies:
            key = getattr(p, attr, "unknown") or "unknown"
            counts[key] = counts.get(key, 0) + 1
        return counts

    def list_all(self) -> List[dict]:
        """Return all proxy info as dict list (for CLI display)."""
        return [p.to_dict() for p in self.proxies]

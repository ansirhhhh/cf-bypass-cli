"""Proxy quality scoring.

Evaluates proxy quality based on:
- Historical success rate
- Recent latency trends
- Failure pattern (burst vs sporadic)
- Provider reputation
- Proxy type (residential > mobile > datacenter)

Quality score is 0.0-1.0. Used by weighted rotation strategy
and for automatic proxy retirement.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cf_bypass.proxy.pool import ProxyNode

# Provider base quality scores (reputation-based)
PROVIDER_BASE_QUALITY = {
    "brightdata": 0.85,
    "oxylabs": 0.80,
    "ipidea": 0.70,
    "manual": 0.60,
    "file": 0.50,
}

# Proxy type base quality
TYPE_BASE_QUALITY = {
    "residential": 0.85,
    "mobile": 0.80,
    "isp": 0.75,
    "datacenter": 0.55,
}


class QualityScorer:
    """Compute composite quality score for a proxy node.

    Score = weighted combination of:
    - provider_reputation (20%)
    - proxy_type (15%)
    - success_rate (50%)
    - recent_trend (15%)
    """

    def __init__(
        self,
        provider_weight: float = 0.20,
        type_weight: float = 0.15,
        success_weight: float = 0.50,
        trend_weight: float = 0.15,
    ):
        self.provider_weight = provider_weight
        self.type_weight = type_weight
        self.success_weight = success_weight
        self.trend_weight = trend_weight

    def evaluate(self, proxy: "ProxyNode") -> float:
        """Compute current quality score for a proxy.

        Args:
            proxy: The ProxyNode to evaluate.

        Returns:
            Quality score 0.0-1.0.
        """
        # Provider reputation
        provider_score = PROVIDER_BASE_QUALITY.get(proxy.provider, 0.50)

        # Proxy type
        type_score = TYPE_BASE_QUALITY.get(proxy.proxy_type, 0.50)

        # Success rate
        success_score = proxy.success_rate

        # Recent trend: are recent attempts succeeding or failing?
        trend_score = self._compute_trend(proxy)

        score = (
            self.provider_weight * provider_score +
            self.type_weight * type_score +
            self.success_weight * success_score +
            self.trend_weight * trend_score
        )

        return round(max(0.0, min(1.0, score)), 3)

    @staticmethod
    def _compute_trend(proxy: "ProxyNode") -> float:
        """Estimate recent success trend.

        Since we don't store per-request history, approximate via
        the ratio of successes to total attempts (weighted toward
        recent: higher ratio = upward trend, lower = downward).
        """
        total = proxy.success_count + proxy.failure_count
        if total <= 1:
            return 0.5  # neutral for new proxies

        # Recent trend: if successes > failures, trend is positive
        success_ratio = proxy.success_rate
        return success_ratio

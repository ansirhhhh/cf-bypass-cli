"""Proxy rotation strategies.

Provides 4 selection algorithms for the proxy pool:

1. **round_robin** — strict sequential order (debug/test)
2. **random** — uniform random from eligible set
3. **weighted** — weighted by quality_score × success_rate (production default)
4. **least_used** — select the proxy used least recently (long sessions)
"""

import random
from abc import ABC, abstractmethod
from typing import List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from cf_bypass.proxy.pool import ProxyNode, ProxyPool


class RotationStrategy(ABC):
    """Abstract base for proxy rotation algorithms."""

    @abstractmethod
    def select(
        self,
        candidates: List["ProxyNode"],
        pool: "ProxyPool" = None,
    ) -> Optional["ProxyNode"]:
        """Select one proxy from the candidates list.

        Args:
            candidates: Pre-filtered list of eligible proxies (already
                        filtered by availability, geo, quality, etc.).
            pool: Reference to the parent pool (for stateful strategies).

        Returns:
            The selected ProxyNode, or None if candidates is empty.
        """
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Strategy identifier."""
        ...


class RoundRobinStrategy(RotationStrategy):
    """Select proxies in strict sequential order.

    State is stored on the pool's `_round_robin_index` counter.
    """

    @property
    def name(self) -> str:
        return "round_robin"

    def select(self, candidates, pool=None) -> Optional["ProxyNode"]:
        if not candidates:
            return None
        if pool is None:
            return candidates[0]

        idx = getattr(pool, "_round_robin_index", 0) % len(candidates)
        pool._round_robin_index = idx + 1
        return candidates[idx]


class RandomStrategy(RotationStrategy):
    """Uniform random selection from eligible proxies."""

    @property
    def name(self) -> str:
        return "random"

    def select(self, candidates, pool=None) -> Optional["ProxyNode"]:
        if not candidates:
            return None
        return random.choice(candidates)


class WeightedStrategy(RotationStrategy):
    """Weighted random selection by proxy quality/success_rate.

    Higher weight = more likely to be selected. This naturally
    phases out low-quality proxies without explicit removal.
    """

    @property
    def name(self) -> str:
        return "weighted"

    def select(self, candidates, pool=None) -> Optional["ProxyNode"]:
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]

        weights = [max(p.weight, 0.01) for p in candidates]
        total = sum(weights)

        if total == 0:
            return random.choice(candidates)

        # Roulette wheel selection
        r = random.uniform(0, total)
        cumulative = 0.0
        for proxy, weight in zip(candidates, weights):
            cumulative += weight
            if r <= cumulative:
                return proxy

        return candidates[-1]


class LeastUsedStrategy(RotationStrategy):
    """Select the proxy that was used least recently.

    Best for long-running sessions where you want to distribute
    load evenly across all available proxies.
    """

    @property
    def name(self) -> str:
        return "least_used"

    def select(self, candidates, pool=None) -> Optional["ProxyNode"]:
        if not candidates:
            return None

        # Sort by last_used (None = never used, goes first)
        def sort_key(p):
            if p.last_used is None:
                return 0.0
            return p.last_used.timestamp()

        candidates.sort(key=sort_key)
        return candidates[0]


# ======================================================================
# Factory
# ======================================================================

_strategy_registry = {
    "round_robin": RoundRobinStrategy(),
    "random": RandomStrategy(),
    "weighted": WeightedStrategy(),
    "least_used": LeastUsedStrategy(),
}


def get_rotation_strategy(name: str) -> RotationStrategy:
    """Get a rotation strategy by name.

    Args:
        name: One of "round_robin", "random", "weighted", "least_used".

    Returns:
        RotationStrategy instance (shared singleton per strategy).
    """
    strategy = _strategy_registry.get(name)
    if strategy is None:
        raise ValueError(
            f"Unknown rotation strategy: {name}. "
            f"Available: {list(_strategy_registry.keys())}"
        )
    return strategy

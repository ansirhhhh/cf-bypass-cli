"""Strategy registry — auto-discovers and registers all bypass strategies."""

from typing import List, Optional

from cf_bypass.strategies.base import BaseStrategy
from cf_bypass.strategies.level1_cloudscraper import Level1Cloudscraper
from cf_bypass.strategies.level2_curl_cffi import Level2CurlCffi
from cf_bypass.strategies.level3_playwright import Level3Playwright
from cf_bypass.strategies.level4_nodriver import Level4Nodriver


class StrategyRegistry:
    """Central registry for all available bypass strategies.

    Strategies are instantiated once at module import time and shared
    across all orchestrator instances.
    """

    _strategies: List[BaseStrategy] = []
    _by_name: dict[str, BaseStrategy] = {}

    @classmethod
    def register(cls, strategy: BaseStrategy) -> None:
        """Register a strategy instance."""
        cls._strategies.append(strategy)
        cls._by_name[strategy.name] = strategy

    @classmethod
    def get_all(cls) -> List[BaseStrategy]:
        """Return all registered strategies (unsorted)."""
        return list(cls._strategies)

    @classmethod
    def get_by_name(cls, name: str) -> Optional[BaseStrategy]:
        """Look up a strategy by its human-readable name."""
        return cls._by_name.get(name)

    @classmethod
    def get_by_level(cls, level: int) -> Optional[BaseStrategy]:
        """Look up a strategy by its level number (1-4)."""
        for s in cls._strategies:
            if s.level == level:
                return s
        return None

    @classmethod
    def get_enabled(cls, enabled_names: List[str]) -> List[BaseStrategy]:
        """Return strategies matching the given names, sorted by level."""
        selected = [cls._by_name[name] for name in enabled_names if name in cls._by_name]
        return sorted(selected, key=lambda s: s.level)


# Auto-register all available strategies
StrategyRegistry.register(Level1Cloudscraper())
StrategyRegistry.register(Level2CurlCffi())
StrategyRegistry.register(Level3Playwright())
StrategyRegistry.register(Level4Nodriver())

__all__ = ["StrategyRegistry", "BaseStrategy"]

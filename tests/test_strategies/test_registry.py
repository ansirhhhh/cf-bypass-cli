"""Tests for StrategyRegistry."""

from cf_bypass.strategies import StrategyRegistry


class TestStrategyRegistry:
    def test_all_strategies_registered(self):
        """All 4 strategies should be auto-registered at import time."""
        all_strategies = StrategyRegistry.get_all()
        assert len(all_strategies) == 4

        names = {s.name for s in all_strategies}
        assert names == {"cloudscraper", "curl_cffi", "playwright", "nodriver"}

        levels = {s.level for s in all_strategies}
        assert levels == {1, 2, 3, 4}

    def test_get_by_name(self):
        s = StrategyRegistry.get_by_name("cloudscraper")
        assert s is not None
        assert s.level == 1

        s = StrategyRegistry.get_by_name("playwright")
        assert s is not None
        assert s.level == 3

    def test_get_by_name_missing(self):
        assert StrategyRegistry.get_by_name("nonexistent") is None

    def test_get_by_level(self):
        s = StrategyRegistry.get_by_level(1)
        assert s is not None
        assert s.name == "cloudscraper"

        s = StrategyRegistry.get_by_level(4)
        assert s is not None
        assert s.name == "nodriver"

        assert StrategyRegistry.get_by_level(99) is None

    def test_get_enabled_filters_and_sorts(self):
        """get_enabled should filter by name and sort by level."""
        enabled = StrategyRegistry.get_enabled(["nodriver", "cloudscraper"])
        assert len(enabled) == 2
        assert enabled[0].name == "cloudscraper"  # level 1
        assert enabled[1].name == "nodriver"       # level 4

    def test_get_enabled_unknown_skipped(self):
        """Unknown strategy names should be silently skipped."""
        enabled = StrategyRegistry.get_enabled(["cloudscraper", "made-up"])
        assert len(enabled) == 1
        assert enabled[0].name == "cloudscraper"

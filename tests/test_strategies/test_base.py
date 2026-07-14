"""Tests for base strategy classes and BypassResult."""

import pytest

from cf_bypass.strategies.base import BypassResult, BaseStrategy


class TestBypassResult:
    def test_defaults(self):
        result = BypassResult(success=True)
        assert result.success is True
        assert result.html is None
        assert result.cookies == {}
        assert result.strategy_name == ""
        assert result.level == 0
        assert result.duration == 0.0
        assert result.error is None
        assert result.status_code is None

    def test_full_result(self):
        result = BypassResult(
            success=True,
            html="<html></html>",
            cookies={"cf_clearance": "x"},
            strategy_name="test",
            level=1,
            duration=3.14,
            status_code=200,
            error="no error",
        )
        assert result.strategy_name == "test"
        assert result.level == 1
        assert result.duration == 3.14


class TestBaseStrategy:
    def test_cannot_instantiate_directly(self):
        """BaseStrategy is abstract and cannot be instantiated."""
        with pytest.raises(TypeError):
            BaseStrategy()  # type: ignore[abstract]

    def test_concrete_subclass(self):
        """A fully implemented subclass should instantiate."""

        class TestStrategy(BaseStrategy):
            @property
            def name(self) -> str:
                return "test"

            @property
            def level(self) -> int:
                return 99

            async def bypass(self, url, proxy=None, timeout=60, headless=False, existing_cookies=None):
                return BypassResult(success=True)

        strat = TestStrategy()
        assert strat.name == "test"
        assert strat.level == 99

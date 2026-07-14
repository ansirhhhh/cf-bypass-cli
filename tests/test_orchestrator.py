"""Tests for Orchestrator — strategy chain, caching, success detection."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cf_bypass.orchestrator import Orchestrator, is_bypass_successful
from cf_bypass.strategies.base import BypassResult


# ---------------------------------------------------------------------------
#  Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_cookie_manager():
    cm = AsyncMock()
    cm.get_valid_cookies.return_value = None
    cm.validate_cookies = AsyncMock(return_value=False)
    cm.store = AsyncMock()
    cm.update_last_used = AsyncMock()
    return cm


@pytest.fixture
def mock_config():
    config = MagicMock()
    config.enabled_strategies = ["cloudscraper", "curl_cffi", "playwright", "nodriver"]
    config.timeout = 60
    config.headless = False
    config.storage_path = "/tmp/test_cf_cookies"
    config.proxy.get_url.return_value = None
    return config


# ---------------------------------------------------------------------------
#  is_bypass_successful — pure function
# ---------------------------------------------------------------------------


class TestIsBypassSuccessful:
    def test_successful(self):
        result = BypassResult(
            success=True,
            html="<html>Real content</html>",
            cookies={"cf_clearance": "abc"},
            status_code=200,
        )
        assert is_bypass_successful(result) is True

    def test_challenge_page_detected(self):
        result = BypassResult(
            success=True,
            html="<html>Just a moment...</html>",
            cookies={"cf_clearance": "abc"},
            status_code=200,
        )
        assert is_bypass_successful(result) is False

    def test_no_cf_clearance(self):
        result = BypassResult(
            success=True,
            html="<html>Real content</html>",
            cookies={"other_cookie": "value"},
            status_code=200,
        )
        assert is_bypass_successful(result) is False

    def test_403_status(self):
        result = BypassResult(
            success=True,
            html="<html>Real content</html>",
            cookies={"cf_clearance": "abc"},
            status_code=403,
        )
        assert is_bypass_successful(result) is False

    def test_not_success(self):
        result = BypassResult(
            success=False,
            error="Something broke",
        )
        assert is_bypass_successful(result) is False

    @pytest.mark.parametrize(
        "indicator",
        [
            "Just a moment...",
            "Checking your browser",
            "cf-browser-verification",
            "challenge-platform",
            "Cloudflare Ray ID:",
        ],
    )
    def test_challenge_indicators(self, indicator):
        html = f"<html><body>{indicator}</body></html>"
        result = BypassResult(
            success=True,
            html=html,
            cookies={"cf_clearance": "abc"},
            status_code=200,
        )
        assert is_bypass_successful(result) is False


# ---------------------------------------------------------------------------
#  Orchestrator — strategy chain
# ---------------------------------------------------------------------------


class TestOrchestratorFallback:
    @pytest.mark.asyncio
    async def test_l1_fails_l2_succeeds(self, mock_cookie_manager, mock_config):
        """L1 returns challenge page, L2 returns real content."""
        orchestrator = Orchestrator(mock_cookie_manager, mock_config)

        l1 = AsyncMock()
        l1.name = "cloudscraper"
        l1.level = 1
        l1.bypass.return_value = BypassResult(
            success=True,
            html="<html>Just a moment...</html>",
            cookies={"cf_clearance": "abc"},
            status_code=200,
            strategy_name="cloudscraper",
            level=1,
        )

        l2 = AsyncMock()
        l2.name = "curl_cffi"
        l2.level = 2
        l2.bypass.return_value = BypassResult(
            success=True,
            html="<html>Real content</html>",
            cookies={"cf_clearance": "real_token"},
            status_code=200,
            strategy_name="curl_cffi",
            level=2,
        )

        orchestrator._strategies = [l1, l2]

        result = await orchestrator.bypass("https://example.com")

        assert result.success is True
        assert result.strategy_name == "curl_cffi"
        l1.bypass.assert_awaited_once()
        l2.bypass.assert_awaited_once()
        mock_cookie_manager.store.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_all_strategies_fail(self, mock_cookie_manager, mock_config):
        """Every strategy returns failure."""
        orchestrator = Orchestrator(mock_cookie_manager, mock_config)

        l1 = AsyncMock()
        l1.name = "cloudscraper"
        l1.level = 1
        l1.bypass.return_value = BypassResult(
            success=False, error="Network error",
            strategy_name="cloudscraper", level=1,
        )

        orchestrator._strategies = [l1]

        result = await orchestrator.bypass("https://example.com")

        assert result.success is False
        assert result.strategy_name == "all_failed"
        assert "Network error" in (result.error or "")

    @pytest.mark.asyncio
    async def test_strategy_exception_caught(self, mock_cookie_manager, mock_config):
        """A strategy that throws should not crash the orchestrator."""
        orchestrator = Orchestrator(mock_cookie_manager, mock_config)

        l1 = AsyncMock()
        l1.name = "cloudscraper"
        l1.level = 1
        l1.bypass.side_effect = RuntimeError("Unexpected crash")

        l2 = AsyncMock()
        l2.name = "curl_cffi"
        l2.level = 2
        l2.bypass.return_value = BypassResult(
            success=True,
            html="<html>Real content</html>",
            cookies={"cf_clearance": "saved"},
            status_code=200,
            strategy_name="curl_cffi",
            level=2,
        )

        orchestrator._strategies = [l1, l2]

        result = await orchestrator.bypass("https://example.com")

        assert result.success is True
        assert result.strategy_name == "curl_cffi"
        l2.bypass.assert_awaited_once()


# ---------------------------------------------------------------------------
#  Orchestrator — cookie caching
# ---------------------------------------------------------------------------


class TestOrchestratorCaching:
    @pytest.mark.asyncio
    async def test_valid_cache_skips_strategies(self, mock_config):
        """Valid cached cookies should bypass the strategy chain entirely."""
        cm = AsyncMock()
        cm.get_valid_cookies.return_value = {"cf_clearance": "valid_token"}
        cm.validate_cookies = AsyncMock(return_value=True)
        cm.update_last_used = AsyncMock()

        orchestrator = Orchestrator(cm, mock_config)

        # Mock strategies that should NOT be called
        for s in orchestrator._strategies:
            s.bypass = AsyncMock(
                side_effect=AssertionError("Strategies should not be called")
            )

        # Also mock _make_request_with_cookies to return success
        async def fake_request(url, cookies, proxy=None, timeout=60):
            return BypassResult(
                success=True,
                html="<html>Cached</html>",
                cookies=cookies,
                status_code=200,
            )

        orchestrator._make_request_with_cookies = fake_request

        result = await orchestrator.bypass("https://example.com")

        assert result.success is True
        cm.update_last_used.assert_awaited_once_with("example.com")

    @pytest.mark.asyncio
    async def test_expired_cache_triggers_strategies(self, mock_config):
        """Expired cache should cause fallback to strategy chain."""
        cm = AsyncMock()
        cm.get_valid_cookies.return_value = None  # No cache
        cm.store = AsyncMock()

        orchestrator = Orchestrator(cm, mock_config)

        l1 = AsyncMock()
        l1.name = "cloudscraper"
        l1.level = 1
        l1.bypass.return_value = BypassResult(
            success=True,
            html="<html>Fresh content</html>",
            cookies={"cf_clearance": "new_token"},
            status_code=200,
            strategy_name="cloudscraper",
            level=1,
        )

        orchestrator._strategies = [l1]

        result = await orchestrator.bypass("https://example.com")

        assert result.success is True
        l1.bypass.assert_awaited_once()
        cm.store.assert_awaited_once_with("example.com", {"cf_clearance": "new_token"})


# ---------------------------------------------------------------------------
#  Orchestrator — cookie_only mode
# ---------------------------------------------------------------------------


class TestOrchestratorCookieOnly:
    @pytest.mark.asyncio
    async def test_cookie_only_strips_html(self, mock_cookie_manager, mock_config):
        """cookie_only=True should return cookies but no HTML."""
        orchestrator = Orchestrator(mock_cookie_manager, mock_config)

        l1 = AsyncMock()
        l1.name = "cloudscraper"
        l1.level = 1
        l1.bypass.return_value = BypassResult(
            success=True,
            html="<html>Huge page content...</html>",
            cookies={"cf_clearance": "tok", "__cf_bm": "bm"},
            status_code=200,
            strategy_name="cloudscraper",
            level=1,
        )

        orchestrator._strategies = [l1]

        result = await orchestrator.bypass("https://example.com", cookie_only=True)

        assert result.success is True
        assert result.html is None
        assert result.cookies == {"cf_clearance": "tok", "__cf_bm": "bm"}

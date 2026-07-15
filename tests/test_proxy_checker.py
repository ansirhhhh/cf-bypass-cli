"""Tests for proxy health checker."""

import pytest
from cf_bypass.proxy_checker import ProxyChecker, ProxyHealth


class TestProxyHealth:
    """Tests for the ProxyHealth dataclass."""

    def test_defaults(self):
        health = ProxyHealth(healthy=True)
        assert health.healthy is True
        assert health.latency_ms == 0.0
        assert health.ip == ""
        assert health.country == ""
        assert health.error is None

    def test_geo_match_exact(self):
        health = ProxyHealth(healthy=True, country="AU")
        assert health.geo_match("AU") is True

    def test_geo_match_case_insensitive(self):
        health = ProxyHealth(healthy=True, country="au")
        assert health.geo_match("AU") is True

    def test_geo_match_mismatch(self):
        health = ProxyHealth(healthy=True, country="US")
        assert health.geo_match("AU") is False

    def test_geo_match_no_requirement(self):
        health = ProxyHealth(healthy=True, country="US")
        assert health.geo_match("") is True

    def test_unhealthy_with_error(self):
        health = ProxyHealth(
            healthy=False,
            latency_ms=150.5,
            error="Connection refused",
        )
        assert health.healthy is False
        assert health.latency_ms == 150.5
        assert health.error == "Connection refused"


class TestProxyChecker:
    """Tests for ProxyChecker async methods."""

    @pytest.mark.asyncio
    async def test_check_latency_unreachable(self):
        """Verify that an invalid proxy returns unhealthy."""
        health = await ProxyChecker.check_latency(
            "http://127.0.0.1:1", timeout=1.0
        )
        assert health.healthy is False
        assert health.error is not None

    @pytest.mark.asyncio
    async def test_full_check_passes_through(self):
        """full_check delegates to check_geo."""
        health = await ProxyChecker.full_check(
            "http://127.0.0.1:1", geo_required="AU", timeout=1.0
        )
        # Should be unhealthy (proxy unreachable)
        assert health.healthy is False

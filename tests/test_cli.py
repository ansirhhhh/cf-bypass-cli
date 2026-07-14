"""Tests for CLI commands using Click's CliRunner."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from cf_bypass.cli import cli
from cf_bypass.strategies.base import BypassResult


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def mock_bypass_success():
    """Orchestrator.bypass returns a successful result."""
    return BypassResult(
        success=True,
        html="<html><body>Hello World</body></html>",
        cookies={"cf_clearance": "abc123", "__cf_bm": "xyz"},
        strategy_name="playwright",
        level=3,
        duration=5.2,
        status_code=200,
    )


@pytest.fixture
def mock_bypass_failure():
    """Orchestrator.bypass returns a failure result."""
    return BypassResult(
        success=False,
        error="All strategies failed. Last error: timeout.",
        strategy_name="all_failed",
    )


class TestBypassCommand:
    def test_bypass_outputs_html(self, runner, mock_bypass_success):
        """Default bypass prints the HTML content."""
        with patch("cf_bypass.cli.Orchestrator") as MockOrch:
            instance = MockOrch.return_value
            instance.bypass = AsyncMock(return_value=mock_bypass_success)
            instance.shutdown = AsyncMock()

            result = runner.invoke(cli, ["bypass", "https://example.com"])

            assert result.exit_code == 0
            assert "Hello World" in result.output

    def test_cookie_only_outputs_json(self, runner, mock_bypass_success):
        """--cookie-only prints cookies as JSON."""
        with patch("cf_bypass.cli.Orchestrator") as MockOrch:
            instance = MockOrch.return_value
            instance.bypass = AsyncMock(return_value=mock_bypass_success)
            instance.shutdown = AsyncMock()

            result = runner.invoke(cli, ["bypass", "--cookie-only", "https://example.com"])

            assert result.exit_code == 0
            parsed = json.loads(result.output)
            assert parsed["cf_clearance"] == "abc123"

    def test_bypass_failure_exits_nonzero(self, runner, mock_bypass_failure):
        """Bypass failure exits with code 1."""
        with patch("cf_bypass.cli.Orchestrator") as MockOrch:
            instance = MockOrch.return_value
            instance.bypass = AsyncMock(return_value=mock_bypass_failure)
            instance.shutdown = AsyncMock()

            result = runner.invoke(cli, ["bypass", "https://example.com"])

            assert result.exit_code == 1
            assert "Error:" in result.output or "timeout" in result.output


class TestStatusCommand:
    def test_no_cookies(self, runner):
        """Status with empty cookie store."""
        with patch("cf_bypass.cli.CookieManager") as MockCM:
            instance = MockCM.return_value
            instance.list_all = AsyncMock(return_value=[])

            result = runner.invoke(cli, ["status"])

            assert result.exit_code == 0
            assert "No stored cookies" in result.output

    def test_with_cookies(self, runner):
        """Status with some stored cookies."""
        with patch("cf_bypass.cli.CookieManager") as MockCM:
            instance = MockCM.return_value
            instance.list_all = AsyncMock(return_value=[
                {
                    "domain": "example.com",
                    "cookie_count": 2,
                    "created_at": "2026-07-14T10:00:00+00:00",
                    "expires_at": "2026-07-15T10:00:00+00:00",
                    "last_used": "2026-07-14T10:30:00+00:00",
                    "has_cf_clearance": True,
                },
            ])

            result = runner.invoke(cli, ["status"])

            assert result.exit_code == 0
            assert "example.com" in result.output
            assert "YES" in result.output


class TestClearCommand:
    def test_clear_all_confirm_no(self, runner):
        """Clear all with 'no' confirmation aborts."""
        with patch("cf_bypass.cli.CookieManager") as MockCM:
            instance = MockCM.return_value
            instance.list_all = AsyncMock(return_value=[
                {"domain": "example.com", "cookie_count": 2}
            ])

            result = runner.invoke(cli, ["clear"], input="n\n")

            assert "Aborted" in result.output
            # clear_all should NOT have been called
            instance.clear_all.assert_not_called()

    def test_clear_domain(self, runner):
        """Clear specific domain."""
        with patch("cf_bypass.cli.CookieManager") as MockCM:
            instance = MockCM.return_value
            instance.clear_domain = AsyncMock(return_value=True)

            result = runner.invoke(cli, ["clear", "--domain", "example.com"])

            assert result.exit_code == 0
            assert "Cleared cookies" in result.output


class TestHelp:
    def test_help_text(self, runner):
        """Main help shows available commands."""
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "bypass" in result.output
        assert "serve" in result.output
        assert "status" in result.output
        assert "clear" in result.output
        assert "batch" in result.output

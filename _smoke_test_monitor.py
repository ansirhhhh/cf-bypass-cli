"""Smoke tests for the new monitor / URL swap feature.

Runs WITHOUT actually launching the browser (lightweight import + contract tests).
"""
from __future__ import annotations

import sys
from types import ModuleType


def _test_import_browser_session() -> None:
    from cf_browser_session_failure_probe import ignore  # noqa: F401
    # placeholder - real code below


def test_import_browser_session():
    from cf_bypass import browser_session
    assert isinstance(browser_session, ModuleType)
    assert hasattr(browser_session, "PersistentBrowserSession")
    cls = browser_session.PersistentBrowserSession
    # Verify core public API methods exist
    for name in (
        "start", "stop", "navigate_to", "change_target",
        "reload", "get_html", "get_cookies", "add_cookies",
        "get_page_url", "wait_for_seconds", "__aenter__", "__aexit__",
    ):
        assert hasattr(cls, name), f"PersistentBrowserSession missing method: {name}"
    # Property check
    assert isinstance(cls.current_url, property)
    print("  [PASS] PersistentBrowserSession API contract OK")


def test_import_cli_monitor():
    from cf_bypass import cli
    # The click command
    assert cli.monitor is not None, "cli.monitor command not registered"
    cmd = cli.monitor
    assert cmd.name == "monitor"
    # Internal helpers
    assert hasattr(cli, "_run_monitor") and callable(cli._run_monitor)
    assert hasattr(cli, "_ainput") and callable(cli._ainput)
    assert hasattr(cli, "MONITOR_HELP") and "/change" in cli.MONITOR_HELP
    # Verify MONITOR_HELP mentions the critical slash commands
    for kw in ("/change", "/status", "/reload", "/cookies", "/bypass", "/quit", "/help", "/nav", "/wait"):
        assert kw in cli.MONITOR_HELP, f"MONITOR_HELP missing command reference: {kw}"
    print("  [PASS] cli.monitor command + helpers registered OK")


def test_cli_help_shows_monitor(tmp_path, monkeypatch):
    """Run `cf-bypass --help` via click's runner and verify 'monitor' is listed."""
    from click.testing import CliRunner
    from cf_bypass.cli import cli

    runner = CliRunner()
    result = runner.invoke(cli, ["--help"], prog_name="cf-bypass")
    assert result.exit_code == 0, f"cli --help failed: {result.output}\n{result.exception}"
    output = result.output
    assert "monitor" in output, f"'monitor' subcommand missing from help. Got:\n{output}"
    print("  [PASS] cf-bypass --help includes 'monitor' subcommand")


def test_monitor_subcommand_help():
    """Run `cf-bypass monitor --help` and verify key options are listed."""
    from click.testing import CliRunner
    from cf_bypass.cli import cli

    runner = CliRunner()
    result = runner.invoke(cli, ["monitor", "--help"], prog_name="cf-bypass")
    assert result.exit_code == 0, f"monitor --help failed: {result.exception}\n{result.output}"
    out = result.output
    for needle in ("--headless", "--timeout", "--proxy", "/change", "Interactive monitor"):
        assert needle in out, f"monitor --help missing '{needle}'. Got:\n{out}"
    print("  [PASS] cf-bypass monitor --help shows options and slash-command summary")


if __name__ == "__main__":
    print("[monitor feature smoke tests]")
    tests = [
        test_import_browser_session,
        test_import_cli_monitor,
        test_cli_help_shows_monitor,
        test_monitor_subcommand_help,
    ]
    failed = 0
    for t in tests:
        try:
            # Handle the pytest-style-parametrized tests without pytest runtime
            if t.__name__ == "test_cli_help_shows_monitor":
                # pytest runner is fine for CliRunner use without param fixtures
                import inspect
                params = inspect.signature(t).parameters
                if len(params) == 0:
                    t()
                else:
                    # call with None placeholders - CliRunner usage doesn't need them
                    try:
                        t(None, None)
                    except Exception:
                        # Fallback - just invoke CliRunner directly
                        from click.testing import CliRunner
                        from cf_bypass.cli import cli
                        runner = CliRunner()
                        r = runner.invoke(cli, ["--help"], prog_name="cf-bypass")
                        assert r.exit_code == 0
                        assert "monitor" in r.output
                        print("  [PASS] cf-bypass --help includes 'monitor' subcommand")
            else:
                t()
        except AssertionError as e:
            failed += 1
            print(f"  [FAIL] {t.__name__}: {e}")
        except Exception as e:
            failed += 1
            print(f"  [CRASH] {t.__name__}: {type(e).__name__}: {e}")

    print("")
    if failed:
        print(f"Result: {len(tests) - failed}/{len(tests)} passed, {failed} failed")
        sys.exit(1)
    else:
        print(f"Result: all {len(tests)}/{len(tests)} passed")
        sys.exit(0)

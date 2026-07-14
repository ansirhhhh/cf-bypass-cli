"""CLI entry point for cf-bypass-cli.

Provides seven commands:

    cf-bypass <url>              Single URL bypass (prints HTML)
    cf-bypass --cookie-only <url> Print cookies as JSON
    cf-bypass serve              Start HTTP API server
    cf-bypass status             Show stored cookies
    cf-bypass clear              Delete cached cookies
    cf-bypass batch urls.txt     Batch process URLs → CSV
    cf-bypass monitor [url]        Interactive session with /change slash cmd
"""

import sys
import json
import asyncio
from typing import Optional

import click

from cf_bypass.config import Config
from cf_bypass.cookie_manager import CookieManager
from cf_bypass.orchestrator import Orchestrator
from cf_bypass.logging_config import setup_logging, get_logger
from cf_bypass.utils import normalize_url

logger = get_logger("cli")


# ======================================================================
#  Async helpers
# ======================================================================


async def _run_bypass(
    url: str,
    cookie_only: bool,
    timeout: int,
    proxy: Optional[str],
    config: Config,
    keep_open: bool = False,
) -> None:
    """Shared async helper for the ``bypass`` and ``--cookie-only`` paths."""
    url = normalize_url(url)
    cookie_manager = CookieManager(config.storage_path)
    orchestrator = Orchestrator(cookie_manager, config)

    try:
        result = await orchestrator.bypass(
            url=url,
            cookie_only=cookie_only,
            proxy=proxy,
            timeout=timeout,
            keep_open=keep_open,
        )

        if not result.success:
            click.echo(f"Error: {result.error}", err=True)
            raise SystemExit(1)

        if cookie_only:
            click.echo(json.dumps(result.cookies, indent=2, ensure_ascii=False))
        else:
            if result.html:
                click.echo(result.html)

        # If keep_open, pause so the user can interact with the browser
        if keep_open and not cookie_only:
            click.echo("")
            click.echo("Browser is kept open. Press Enter to close it...")
            try:
                input()
            except (EOFError, KeyboardInterrupt):
                click.echo("")

    finally:
        await orchestrator.shutdown()


# ======================================================================
#  CLI group
# ======================================================================


@click.group()
@click.option(
    "--config", "-c",
    type=click.Path(exists=True, dir_okay=False),
    help="Path to config YAML file.",
)
@click.option(
    "--verbose", "-v",
    is_flag=True,
    help="Enable DEBUG-level logging.",
)
@click.pass_context
def cli(ctx: click.Context, config: Optional[str], verbose: bool) -> None:
    """cf-bypass-cli — Progressive Cloudflare WAF bypass tool.

    A local CLI tool that uses progressive fallback strategies to
    automatically bypass Cloudflare anti-bot challenges.

    \b
    Strategies (tried in order):
      L1  cloudscraper      Lightweight JS challenge solver
      L2  curl_cffi         TLS fingerprint impersonation
      L3  playwright        Full browser + stealth patches
      L4  nodriver          CDP-level stealth (ultimate fallback)
    """
    ctx.ensure_object(dict)
    level = "DEBUG" if verbose else "INFO"
    setup_logging(level)
    ctx.obj["config"] = Config.load(config) if config else Config.load()


# ======================================================================
#  bypass — single URL
# ======================================================================


@cli.command()
@click.argument("url")
@click.option(
    "--cookie-only",
    is_flag=True,
    help="Print cookies as JSON instead of HTML content.",
)
@click.option(
    "--timeout", "-t",
    default=60,
    type=int,
    show_default=True,
    help="Timeout in seconds.",
)
@click.option(
    "--proxy", "-p",
    default=None,
    help="Proxy URL (http://user:pass@host:port).",
)
@click.option(
    "--keep-open", "-k",
    is_flag=True,
    help="Keep browser window open after bypass (L3/L4 headed mode).",
)
@click.pass_context
def bypass(
    ctx: click.Context,
    url: str,
    cookie_only: bool,
    timeout: int,
    proxy: Optional[str],
    keep_open: bool,
) -> None:
    """Bypass Cloudflare protection for a single URL.

    Prints the page HTML on success, or a JSON error message on failure.
    Use --cookie-only to get cookies as JSON instead.

    \b
    Examples:
      cf-bypass https://example.com
      cf-bypass --cookie-only https://example.com
      cf-bypass --keep-open https://example.com
      cf-bypass --timeout 120 --proxy http://proxy:8080 https://example.com
    """
    asyncio.run(
        _run_bypass(
            url=url,
            cookie_only=cookie_only,
            timeout=timeout,
            proxy=proxy,
            config=ctx.obj["config"],
            keep_open=keep_open,
        )
    )


# ======================================================================
#  serve — HTTP API
# ======================================================================


@cli.command()
@click.option(
    "--port", "-p",
    default=8191,
    type=int,
    show_default=True,
    help="HTTP API listen port.",
)
@click.option(
    "--host", "-h",
    default="127.0.0.1",
    show_default=True,
    help="Bind address.",
)
@click.pass_context
def serve(ctx: click.Context, port: int, host: str) -> None:
    """Start the HTTP API server.

    Exposes a REST API for bypass requests. Useful when calling from
    scripts, browser extensions, or other tools.

    \b
    Endpoints:
      POST /bypass            Bypass a URL
      GET  /health            Health check
      GET  /cookies           List stored cookies
      DELETE /cookies/{domain} Delete domain cookies

    \b
    Example:
      cf-bypass serve --port 8191
      curl -X POST http://localhost:8191/bypass \\
           -H "Content-Type: application/json" \\
           -d '{"url": "https://example.com"}'
    """
    import uvicorn
    from cf_bypass.server.app import create_app

    app = create_app(ctx.obj["config"])

    click.echo(f"┌─────────────────────────────────────────────┐")
    click.echo(f"│  cf-bypass API server                       │")
    click.echo(f"│  Listening on http://{host}:{port}          │")
    click.echo(f"├─────────────────────────────────────────────┤")
    click.echo(f"│  POST /bypass            Bypass a URL       │")
    click.echo(f"│  GET  /health            Health check       │")
    click.echo(f"│  GET  /cookies           List cookies       │")
    click.echo(f"│  DELETE /cookies/{{domain}} Delete cookies   │")
    click.echo(f"└─────────────────────────────────────────────┘")
    click.echo(f"")
    click.echo(f"Press Ctrl+C to stop.")

    uvicorn.run(app, host=host, port=port, log_level="info")


# ======================================================================
#  status — show stored cookies
# ======================================================================


@cli.command()
@click.pass_context
def status(ctx: click.Context) -> None:
    """Display all stored Cloudflare clearance cookies.

    Shows domain, cookie count, expiry time, and whether a cf_clearance
    cookie is present.
    """

    async def _show() -> None:
        cookie_manager = CookieManager(ctx.obj["config"].storage_path)
        cookies = await cookie_manager.list_all()

        if not cookies:
            click.echo("No stored cookies found.")
            click.echo(f"Storage directory: {cookie_manager.storage_dir}")
            return

        # Table header
        header = f"{'Domain':<30} {'Cookies':<8} {'Expires':<22} {'CF':<5}"
        click.echo(header)
        click.echo("-" * len(header))

        for c in cookies:
            cf_mark = "YES" if c["has_cf_clearance"] else "no"
            expires = c["expires_at"]
            expires_short = expires[:19] if expires else "N/A"
            click.echo(
                f"{c['domain']:<30} {c['cookie_count']:<8} "
                f"{expires_short:<22} {cf_mark:<5}"
            )

        click.echo(f"\nTotal: {len(cookies)} domain(s)")
        click.echo(f"Storage: {cookie_manager.storage_dir}")

    asyncio.run(_show())


# ======================================================================
#  clear — remove cached cookies
# ======================================================================


@cli.command()
@click.option(
    "--domain", "-d",
    default=None,
    help="Clear cookies for a specific domain only.",
)
@click.option(
    "--yes", "-y",
    is_flag=True,
    help="Skip confirmation prompt.",
)
@click.pass_context
def clear(
    ctx: click.Context,
    domain: Optional[str],
    yes: bool,
) -> None:
    """Clear stored Cloudflare cookies.

    Without --domain, clears ALL cached cookies after confirmation.
    With --domain, clears only that domain's cookies.
    """

    async def _clear() -> None:
        cookie_manager = CookieManager(ctx.obj["config"].storage_path)

        if domain:
            deleted = await cookie_manager.clear_domain(domain)
            if deleted:
                click.echo(f"✓ Cleared cookies for {domain}")
            else:
                click.echo(f"No cookies found for {domain}", err=True)
                raise SystemExit(1)
        else:
            cookies = await cookie_manager.list_all()
            if not cookies:
                click.echo("No stored cookies to clear.")
                return

            if not yes:
                click.echo(f"About to delete cookies for {len(cookies)} domain(s):")
                for c in cookies:
                    click.echo(f"  - {c['domain']}")
                if not click.confirm("\nProceed?"):
                    click.echo("Aborted.")
                    return

            count = await cookie_manager.clear_all()
            click.echo(f"✓ Cleared {count} cookie file(s)")

    asyncio.run(_clear())


# ======================================================================
#  batch — process multiple URLs
# ======================================================================


@cli.command()
@click.argument(
    "url_file",
    type=click.Path(exists=True, dir_okay=False),
)
@click.option(
    "--output", "-o",
    default="results.csv",
    show_default=True,
    help="Output CSV file path.",
)
@click.option(
    "--timeout", "-t",
    default=60,
    type=int,
    show_default=True,
    help="Timeout per URL in seconds.",
)
@click.option(
    "--proxy", "-p",
    default=None,
    help="Proxy URL for all requests.",
)
@click.pass_context
def batch(
    ctx: click.Context,
    url_file: str,
    output: str,
    timeout: int,
    proxy: Optional[str],
) -> None:
    """Process multiple URLs from a file (one per line).

    Lines starting with # are treated as comments and skipped.
    Results are written to a CSV file.

    \b
    Example:
      cf-bypass batch urls.txt -o results.csv -t 120
      cf-bypass batch urls.txt --proxy http://proxy:8080
    """
    from cf_bypass.batch.processor import BatchProcessor

    cookie_manager = CookieManager(ctx.obj["config"].storage_path)
    orchestrator = Orchestrator(cookie_manager, ctx.obj["config"])
    processor = BatchProcessor(orchestrator)

    async def _process() -> None:
        results = await processor.process_file(
            input_path=url_file,
            output_path=output,
            timeout=timeout,
            proxy=proxy,
        )
        succeeded = sum(1 for r in results if r["success"])
        click.echo(
            f"\nDone: {succeeded}/{len(results)} succeeded. "
            f"Results saved to {output}"
        )
        await orchestrator.shutdown()

    asyncio.run(_process())


# ======================================================================
#  monitor — interactive persistent session with /change slash command
# ======================================================================


MONITOR_HELP = """\
Available slash commands:
  /change  /c <url>     Prompt for (or directly supply) a new URL; close
                        the current page and open a fresh one on the new URL.
  /nav     /n <url>     Navigate the existing page to a new URL (page stays).
  /status  /s           Print current monitor URL and browser page URL.
  /cookies              Print all cookies from the browser context as JSON.
  /reload  /r           Reload the current page.
  /wait    /w <seconds> Pause for N seconds (useful to watch challenges).
  /bypass  /b           Run the full L1..L4 bypass orchestrator on the
                        current URL and report the result.
  /help    /h           Show this help text.
  /quit    /q           Close the browser and exit.  (Ctrl+C also works.)

Anything that does NOT start with '/' is printed back and ignored.
"""


async def _ainput(prompt: str = "") -> str:
    """Async wrapper around :func:`input` so the REPL stays responsive.

    Uses :func:`asyncio.to_thread` so that while we are blocked waiting
    for the user to type a line, other async tasks (e.g. browser I/O) are
    not starved.
    """
    try:
        return await asyncio.to_thread(input, prompt)
    except EOFError:
        return "/quit"
    except KeyboardInterrupt:
        return "/quit"


async def _run_monitor(
    initial_url: Optional[str],
    cookie_only: bool,
    timeout: int,
    proxy: Optional[str],
    headless: bool,
    config: Config,
) -> None:
    """Implementation body of the ``monitor`` CLI subcommand."""

    # ------------------------------------------------------------------
    # 1. Determine the starting URL (CLI arg or interactive prompt)
    # ------------------------------------------------------------------
    if not initial_url:
        click.echo("")
        click.echo("  Enter the initial target URL to open in the browser.")
        while True:
            raw = await _ainput("  Initial URL (or /q to quit): ")
            raw = raw.strip()
            if raw.lower() in ("/q", "/quit", "quit", "exit", ""):
                click.echo("Aborted.")
                return
            if len(raw) > 4:
                initial_url = raw
                break
            click.echo("  [WARN] That does not look like a URL — try again.")

    initial_url = normalize_url(initial_url)

    # ------------------------------------------------------------------
    # 2. Show welcome banner and start the persistent session
    # ------------------------------------------------------------------
    click.echo("")
    click.echo("  +------------------------------------------------------+")
    click.echo("        cf-bypass-cli  --  INTERACTIVE MONITOR MODE")
    click.echo("  +------------------------------------------------------+")
    click.echo(f"    Target URL : {initial_url}")
    click.echo(f"    Mode       : {'headless' if headless else 'headed browser'}")
    click.echo(f"    Proxy      : {proxy or '(none)'}")
    click.echo(f"    Timeout    : {timeout}s per navigation")
    click.echo("  +------------------------------------------------------+")
    click.echo("  Type /help to see all slash commands.")
    click.echo("  Press Ctrl+C or type /quit to stop.")
    click.echo("")

    from cf_bypass.browser_session import PersistentBrowserSession

    cookie_manager = CookieManager(config.storage_path)
    orchestrator = Orchestrator(cookie_manager, config)

    session = PersistentBrowserSession(proxy=proxy, headless=headless)
    await session.start()

    try:
        ok = await session.change_target(initial_url, timeout=timeout)
        if ok:
            click.echo(f"  [OK]  Page opened: {await session.get_page_url()}")
        else:
            click.echo("  [WARN] Initial navigation returned an error (see log). Continuing anyway — use /change to retry.")

        # --------------------------------------------------------------
        # 3. REPL loop
        # --------------------------------------------------------------
        while True:
            prompt_suffix = (session.current_url or "(no url)").split("://", 1)[-1][:48]
            try:
                line = await _ainput(f"cf-bypass [{prompt_suffix}]> ")
            except Exception:
                line = "/quit"

            line = line.strip()
            if not line:
                continue

            # Slash commands
            if line.startswith("/"):
                parts = line.split(maxsplit=1)
                cmd = parts[0].lower()
                arg = parts[1] if len(parts) > 1 else ""

                # -------------------------------------------------
                # /quit
                # -------------------------------------------------
                if cmd in ("/quit", "/q", "/exit"):
                    click.echo("  Closing browser and exiting...")
                    break

                # -------------------------------------------------
                # /help
                # -------------------------------------------------
                elif cmd in ("/help", "/h", "/?"):
                    click.echo(MONITOR_HELP)

                # -------------------------------------------------
                # /status
                # -------------------------------------------------
                elif cmd in ("/status", "/s"):
                    click.echo(f"    Target (logical) : {session.current_url or '(none)'}")
                    actual = await session.get_page_url()
                    click.echo(f"    Page URL (real)  : {actual or '(no page)'}")
                    cookies = await session.get_cookies()
                    cf = "YES" if "cf_clearance" in {k.lower() for k in cookies} else "no"
                    click.echo(f"    Cookies stored   : {len(cookies)}   cf_clearance: {cf}")

                # -------------------------------------------------
                # /cookies
                # -------------------------------------------------
                elif cmd == "/cookies":
                    cookies = await session.get_cookies()
                    if not cookies:
                        click.echo("    (no cookies yet)")
                    else:
                        click.echo(json.dumps(cookies, indent=2, ensure_ascii=False))

                # -------------------------------------------------
                # /change  [new_url]
                # -------------------------------------------------
                elif cmd in ("/change", "/c"):
                    new_url = arg.strip()
                    if not new_url:
                        new_url = (await _ainput("    New target URL: ")).strip()
                    if not new_url:
                        click.echo("    [WARN] Empty URL — nothing changed.")
                        continue
                    new_url = normalize_url(new_url)

                    # Re-use any stored cached cookies for this domain
                    from urllib.parse import urlparse as _up
                    domain = _up(new_url).netloc
                    cached = await cookie_manager.get_valid_cookies(domain)
                    if cached is not None:
                        await session.add_cookies(cached, for_url=new_url)
                        click.echo(f"    [OK] Injected {len(cached)} cached cookies for {domain}")

                    click.echo(f"    Closing current page and opening -> {new_url}")
                    ok = await session.change_target(new_url, timeout=timeout)
                    if ok:
                        real = await session.get_page_url()
                        click.echo(f"    [OK] New page opened: {real}")
                    else:
                        click.echo("    [WARN] Navigation reported an error (browser window is still open).")

                    # Persist any new cookies so cache stays warm
                    fresh = await session.get_cookies(url=new_url)
                    if fresh:
                        await cookie_manager.store(domain, fresh)

                # -------------------------------------------------
                # /nav <url>    (navigate, keep page alive)
                # -------------------------------------------------
                elif cmd in ("/nav", "/n"):
                    new_url = arg.strip()
                    if not new_url:
                        click.echo("    Usage: /nav <url>")
                        continue
                    new_url = normalize_url(new_url)
                    click.echo(f"    Navigating existing page -> {new_url}")
                    ok = await session.navigate_to(new_url, timeout=timeout)
                    click.echo("    [OK]" if ok else "    [WARN] Navigation reported error.")

                # -------------------------------------------------
                # /reload
                # -------------------------------------------------
                elif cmd in ("/reload", "/r"):
                    click.echo("    Reloading current page...")
                    ok = await session.reload(timeout=timeout)
                    click.echo("    [OK] Reloaded." if ok else "    [WARN] Reload error.")

                # -------------------------------------------------
                # /wait N
                # -------------------------------------------------
                elif cmd in ("/wait", "/w"):
                    try:
                        seconds = float(arg) if arg else 3.0
                    except ValueError:
                        seconds = 3.0
                        click.echo(f"    (bad number, using default {seconds}s)")
                    click.echo(f"    Waiting {seconds}s... (Ctrl+C to resume early)")
                    try:
                        await session.wait_for_seconds(seconds)
                        click.echo("    done.")
                    except KeyboardInterrupt:
                        click.echo("    (early resume)")

                # -------------------------------------------------
                # /bypass   — run orchestrator bypass for current URL
                # -------------------------------------------------
                elif cmd in ("/bypass", "/b"):
                    target = (arg.strip()
                              or session.current_url
                              or await session.get_page_url()
                              or "")
                    if not target:
                        click.echo("    No URL available — use /change <url> first.")
                        continue
                    target = normalize_url(target)
                    click.echo(f"    Running orchestrator bypass for -> {target}")
                    result = await orchestrator.bypass(
                        url=target,
                        cookie_only=cookie_only,
                        proxy=proxy,
                        timeout=timeout,
                        headless=headless,
                    )
                    if not result.success:
                        click.echo(f"    [FAIL] {result.error}")
                    else:
                        cookies = result.cookies
                        cf = "YES" if "cf_clearance" in {k.lower() for k in cookies} else "no"
                        click.echo(
                            f"    [OK]  strategy={result.strategy_name}  "
                            f"status={result.status_code}  "
                            f"duration={result.duration:.1f}s  "
                            f"cf_clearance={cf}  "
                            f"cookies={len(cookies)}"
                        )
                        if not cookie_only and result.html is not None:
                            click.echo(f"    (HTML length: {len(result.html)} chars)")

                # -------------------------------------------------
                # Unknown slash command
                # -------------------------------------------------
                else:
                    click.echo(f"    Unknown command: {cmd}.  Type /help for list.")

            # Not a slash command — ignore silently
            else:
                click.echo("    (input is not a slash command. Type /help for list.)")

    except KeyboardInterrupt:
        click.echo("")
        click.echo("  Caught Ctrl+C — shutting down...")

    finally:
        # Cleanup order matters: session.stop() also closes its page
        try:
            await session.stop()
        except Exception:
            pass
        try:
            await orchestrator.shutdown()
        except Exception:
            pass
        click.echo("  Monitor session ended. Bye.")
        click.echo("")


@cli.command()
@click.argument("url", required=False)
@click.option(
    "--cookie-only",
    is_flag=True,
    help="Make /bypass return cookies instead of HTML.",
)
@click.option(
    "--timeout", "-t",
    default=90,
    type=int,
    show_default=True,
    help="Navigation timeout in seconds.",
)
@click.option(
    "--proxy", "-p",
    default=None,
    help="Proxy URL (http://user:pass@host:port).",
)
@click.option(
    "--headless",
    is_flag=True,
    help="Run browser in headless (invisible) mode.",
)
@click.pass_context
def monitor(
    ctx: click.Context,
    url: Optional[str],
    cookie_only: bool,
    timeout: int,
    proxy: Optional[str],
    headless: bool,
) -> None:
    """Interactive monitor session with hot-swappable URLs.

    Starts a persistent headed Chromium browser on the supplied URL
    (prompts for it interactively if not provided on the command line)
    and drops you into a REPL.

    \b
    Key slash commands
    ------------------
    /change [URL]   Close the CURRENT page, prompt for a new URL,
                    open a FRESH page on that URL.
    /nav <URL>      Re-use the same page (no close).
    /status         Show current target and cookie summary.
    /cookies        Dump all browser cookies as JSON.
    /reload         Reload current page.
    /wait N         Sleep N seconds (watch challenges resolve).
    /bypass         Run the full L1..L4 bypass chain on current URL.
    /help           Full command list.
    /quit           Exit.

    \b
    Examples:
      cf-bypass monitor
      cf-bypass monitor https://example.com
      cf-bypass monitor --proxy http://proxy:8080 -t 120 https://example.com
      cf-bypass monitor --headless https://example.com
    """
    asyncio.run(
        _run_monitor(
            initial_url=url,
            cookie_only=cookie_only,
            timeout=timeout,
            proxy=proxy,
            headless=headless,
            config=ctx.obj["config"],
        )
    )


# ======================================================================
#  Entry point
# ======================================================================


def main() -> None:
    """Programmatic entry point (also used by the console_scripts hook)."""
    # The click group automatically handles --help and subcommand dispatch
    cli(prog_name="cf-bypass")


if __name__ == "__main__":
    main()

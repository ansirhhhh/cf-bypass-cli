"""Progressive strategy orchestrator.

The orchestrator is the brain of cf-bypass-cli.  It manages the full
lifecycle of a bypass request:

1. Check the cookie cache for the target domain.
2. If valid cached cookies exist, try a lightweight reuse.
3. If no cache (or cache invalid), iterate the strategy chain L1→L4.
4. On first success, persist cookies and return BypassResult.
5. If every strategy fails, return a descriptive error result.

Key design property: **exceptions never bubble past the orchestrator.**
Every strategy call is wrapped in try/except, and the caller always
receives a BypassResult — never an unhandled exception.
"""

import time
from typing import Optional, Dict, List

from urllib.parse import urlparse

from cf_bypass.strategies.base import BaseStrategy, BypassResult
from cf_bypass.strategies import StrategyRegistry
from cf_bypass.cookie_manager import CookieManager
from cf_bypass.config import Config
from cf_bypass.logging_config import get_logger

import httpx

logger = get_logger("orchestrator")

# ---------------------------------------------------------------------------
# Challenge indicators — used by is_bypass_successful()
# ---------------------------------------------------------------------------

CF_CHALLENGE_INDICATORS: List[str] = [
    "Just a moment...",
    "Checking your browser",
    "cf-browser-verification",
    "challenge-platform",
    "Attention Required!",
    "Cloudflare Ray ID:",
    "_cf_chl_opt",
    "cf_challenge_response",
    "jschl_vc",
    "jschl_answer",
    "/cdn-cgi/challenge-platform",
    "Enable JavaScript and cookies to continue",
]


def is_bypass_successful(result: BypassResult) -> bool:
    """Determine whether a BypassResult represents a successful Cloudflare bypass.

    Returns True only when ALL of these hold:
    1. ``result.success`` is True (no exception thrown).
    2. ``status_code`` is 200 (or was not set).
    3. Response body does NOT contain known Cloudflare challenge indicators.
    4. A ``cf_clearance`` cookie is present (the canonical proof of bypass).
    """
    if not result.success:
        return False

    if result.status_code is not None and result.status_code != 200:
        return False

    if result.html:
        html_lower = result.html.lower()
        for indicator in CF_CHALLENGE_INDICATORS:
            if indicator.lower() in html_lower:
                return False

    # The presence of cf_clearance is the strongest signal
    cookies_lower = {k.lower(): v for k, v in result.cookies.items()}
    if "cf_clearance" not in cookies_lower:
        return False

    return True


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


class Orchestrator:
    """Progressive strategy chain executor.

    Usage::

        config = Config.load()
        cookie_mgr = CookieManager(config.storage_path)
        orchestrator = Orchestrator(cookie_mgr, config)

        result = await orchestrator.bypass("https://example.com")
        if result.success:
            print(result.html)
        else:
            print(f"Failed: {result.error}")

    Call :meth:`shutdown` before discarding the orchestrator to release
    browser resources held by L3/L4 strategies.
    """

    def __init__(self, cookie_manager: CookieManager, config: Config):
        self.cookie_manager = cookie_manager
        self.config = config
        self._strategies: List[BaseStrategy] = []
        self._load_enabled_strategies()

    # ------------------------------------------------------------------
    #  Strategy loading
    # ------------------------------------------------------------------

    def _load_enabled_strategies(self) -> None:
        """Load strategies from the registry, filtered and sorted by config."""
        self._strategies = StrategyRegistry.get_enabled(
            self.config.enabled_strategies
        )
        names = [s.name for s in self._strategies]
        logger.info(f"Loaded strategies (in order): {names}")

    # ------------------------------------------------------------------
    #  Main entry point
    # ------------------------------------------------------------------

    async def bypass(
        self,
        url: str,
        cookie_only: bool = False,
        proxy: Optional[str] = None,
        timeout: Optional[int] = None,
        headless: Optional[bool] = None,
        keep_open: bool = False,
    ) -> BypassResult:
        """Attempt to bypass Cloudflare for a single URL.

        Parameters
        ----------
        url:
            Target URL (with or without scheme).
        cookie_only:
            If True, strip HTML from the returned result.
        proxy:
            Optional proxy URL.  If None and the config proxy is enabled,
            the config proxy URL is used automatically.
        timeout:
            Per-strategy timeout in seconds.  Falls back to config.timeout.
        headless:
            Browser headless mode.  Falls back to config.headless.
        keep_open:
            If True, browser strategies keep the window open after success.

        Returns
        -------
        BypassResult
            Always returns a result — never raises.
        """
        domain = urlparse(url).netloc or urlparse("https://" + url).netloc
        timeout = timeout if timeout is not None else self.config.timeout
        headless = headless if headless is not None else self.config.headless

        # Resolve proxy (CLI arg > config proxy)
        effective_proxy = proxy or self.config.proxy.get_url()

        # Run proxy health check if configured
        if effective_proxy and self.config.proxy.health_check:
            from cf_bypass.proxy_checker import ProxyChecker
            health = await ProxyChecker.check_latency(
                effective_proxy, timeout=10.0
            )
            if not health.healthy:
                logger.warning(
                    f"Proxy health check failed: {health.error}. "
                    f"Falling back to direct connection."
                )
                effective_proxy = None
            else:
                # Verify geo requirement
                geo = self.config.proxy.geo_required
                if geo and not health.geo_match(geo):
                    logger.warning(
                        f"Proxy geo mismatch: need {geo}, got {health.country}. "
                        f"Falling back to direct connection."
                    )
                    effective_proxy = None
                else:
                    logger.info(
                        f"Proxy OK: {health.ip} ({health.country}), "
                        f"{health.latency_ms:.0f}ms"
                    )

        logger.info(f"Bypass requested: url={url}, domain={domain}, timeout={timeout}")

        # --------------------------------------------------------------
        # Step 1: Try cached cookies (fast path)
        # --------------------------------------------------------------
        cached_cookies = await self.cookie_manager.get_valid_cookies(domain)

        if cached_cookies is not None:
            logger.info(f"Found cached cookies for {domain}, validating...")
            valid = await self.cookie_manager.validate_cookies(
                domain, cached_cookies, url=url, proxy=effective_proxy
            )
            if valid:
                logger.info(f"Cached cookies valid for {domain}, reusing.")
                result = await self._make_request_with_cookies(
                    url, cached_cookies, proxy=effective_proxy, timeout=timeout
                )
                if is_bypass_successful(result):
                    await self.cookie_manager.update_last_used(domain)
                    if cookie_only:
                        result.html = None
                    return result

                logger.info("Cached cookies failed validation test, proceeding to strategy chain")
            else:
                logger.info("Cached cookies invalid, proceeding to strategy chain")

        # --------------------------------------------------------------
        # Step 2: Progressive strategy chain
        # --------------------------------------------------------------
        last_error = None
        strategy_errors: List[str] = []

        for strategy in self._strategies:
            strategy_name = strategy.name
            strategy_level = strategy.level

            # Increase timeout progressively for heavier strategies
            effective_timeout = timeout + (strategy_level - 1) * 10

            logger.info(
                f"Trying L{strategy_level}: {strategy_name} "
                f"(timeout={effective_timeout}s)"
            )

            try:
                result = await strategy.bypass(
                    url=url,
                    proxy=effective_proxy,
                    timeout=effective_timeout,
                    headless=headless,
                    existing_cookies=cached_cookies,
                    keep_open=keep_open,
                )

                if is_bypass_successful(result):
                    logger.info(
                        f"✓ L{strategy_level}: {strategy_name} succeeded "
                        f"in {result.duration:.1f}s"
                    )
                    # Persist cookies for future reuse
                    if result.cookies:
                        await self.cookie_manager.store(domain, result.cookies)
                    if cookie_only:
                        result.html = None
                    return result

                # Strategy completed but bypass was incomplete
                error_detail = result.error or (
                    f"status={result.status_code}, "
                    f"cookies={list(result.cookies.keys())}"
                )
                logger.warning(
                    f"✗ L{strategy_level}: {strategy_name} incomplete — {error_detail}"
                )
                strategy_errors.append(f"  - L{strategy_level} {strategy_name}: {error_detail}")
                last_error = error_detail

            except Exception as exc:
                logger.warning(f"✗ L{strategy_level}: {strategy_name} crashed: {exc}")
                strategy_errors.append(f"  - L{strategy_level} {strategy_name}: {exc}")
                last_error = str(exc)

        # --------------------------------------------------------------
        # Step 3: All strategies exhausted — build a helpful error
        # --------------------------------------------------------------
        suggestions = [
            "Ensure Chrome/Chromium is installed (run: playwright install chromium)",
            "Try a residential proxy (--proxy http://user:pass@proxy:8080)",
            "Use headed mode (set headless: false in config)",
            "Manually verify the site is accessible from your network",
        ]

        error_msg = (
            f"All strategies failed for {url}.\n"
            + "\n".join(strategy_errors)
            + "\n\nSuggestions:\n"
            + "\n".join(f"  * {s}" for s in suggestions)
        )
        logger.error(error_msg)

        return BypassResult(
            success=False,
            error=error_msg,
            strategy_name="all_failed",
        )

    # ------------------------------------------------------------------
    #  Helpers
    # ------------------------------------------------------------------

    async def _make_request_with_cookies(
        self,
        url: str,
        cookies: Dict[str, str],
        proxy: Optional[str] = None,
        timeout: int = 60,
    ) -> BypassResult:
        """Lightweight GET request using cached cookies via httpx.

        Used in the fast-path when cached cookies pass validation.
        """
        client_kwargs: dict = {
            "cookies": cookies,
            "timeout": float(timeout),
            "follow_redirects": True,
        }
        if proxy:
            client_kwargs["proxies"] = proxy

        try:
            async with httpx.AsyncClient(**client_kwargs) as client:
                response = await client.get(url)
                return BypassResult(
                    success=response.status_code == 200,
                    html=response.text,
                    cookies=dict(response.cookies),
                    status_code=response.status_code,
                )
        except Exception as exc:
            return BypassResult(success=False, error=str(exc))

    async def shutdown(self) -> None:
        """Release resources held by all strategies (browsers, etc.)."""
        for strategy in self._strategies:
            try:
                await strategy.cleanup()
            except Exception as exc:
                logger.warning(f"Cleanup error for {strategy.name}: {exc}")

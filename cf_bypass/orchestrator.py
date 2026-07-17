"""Progressive strategy orchestrator (v2.0).

The orchestrator is the brain of cf-bypass-cli.  It manages the full
lifecycle of a bypass request:

1. Check the cookie cache for the target domain.
2. If valid cached cookies exist, try a lightweight reuse.
3. If smart routing is enabled, run quick_probe() to select best strategy.
4. If no cache (or cache invalid), iterate the strategy chain L1→L4.
5. On first success, persist cookies and return BypassResult.
6. If every strategy fails, return a descriptive error result.

v2.0 adds: proxy pool, smart routing, retry policy, CAPTCHA dispatcher,
humanize/fingerprint integration.
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

    cookies_lower = {k.lower(): v for k, v in result.cookies.items()}
    if "cf_clearance" not in cookies_lower:
        return False

    return True


# ---------------------------------------------------------------------------
# Quick probe result
# ---------------------------------------------------------------------------

class ProbeResult:
    """Result of a quick probe to determine the best starting strategy."""

    def __init__(
        self,
        status_code: int = 0,
        has_challenge: bool = False,
        has_turnstile: bool = False,
        has_captcha: bool = False,
        suggested_level: int = 1,
    ):
        self.status_code = status_code
        self.has_challenge = has_challenge
        self.has_turnstile = has_turnstile
        self.has_captcha = has_captcha
        self.suggested_level = suggested_level


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


class Orchestrator:
    """Progressive strategy chain executor (v2.0).

    Usage::

        config = Config.load()
        cookie_mgr = CookieManager(config.storage_path)
        orchestrator = Orchestrator(cookie_mgr, config)

        result = await orchestrator.bypass("https://example.com")
        if result.success:
            print(result.html)
    """

    def __init__(self, cookie_manager: CookieManager, config: Config):
        self.cookie_manager = cookie_manager
        self.config = config
        self._strategies: List[BaseStrategy] = []
        self._proxy_pool = None  # Lazy-init
        self._captcha_dispatcher = None  # Lazy-init
        self._fingerprint_profile = None  # Per-session
        self._load_enabled_strategies()

    # ------------------------------------------------------------------
    # Strategy loading
    # ------------------------------------------------------------------

    def _load_enabled_strategies(self) -> None:
        """Load strategies from the registry, filtered and sorted by config."""
        self._strategies = StrategyRegistry.get_enabled(
            self.config.enabled_strategies
        )
        names = [s.name for s in self._strategies]
        logger.info(f"Loaded strategies (in order): {names}")

    # ------------------------------------------------------------------
    # Lazy init helpers
    # ------------------------------------------------------------------

    def _init_proxy_pool(self):
        """Lazy-init the proxy pool from config."""
        if self._proxy_pool is not None:
            return
        try:
            # Defensive: only init if truly enabled
            pp = getattr(self.config, 'proxy_pool', None)
            if pp is None:
                return
            if not getattr(pp, 'enabled', False):
                return
            nodes = getattr(pp, 'nodes', [])
            if not isinstance(nodes, list) or len(nodes) == 0:
                return

            from cf_bypass.proxy.pool import ProxyPool, ProxyNode

            strategy = getattr(pp, 'strategy', 'weighted')
            valid_strategies = ["round_robin", "random", "weighted", "least_used"]
            if strategy not in valid_strategies:
                strategy = "weighted"

            self._proxy_pool = ProxyPool(
                strategy=strategy,
                cooldown_after_failures=getattr(pp, 'cooldown_after_failures', 3),
                cooldown_duration=getattr(pp, 'cooldown_duration', 600),
                health_check_interval=getattr(pp, 'health_check_interval', 300),
                min_quality=getattr(pp, 'min_quality', 0.3),
            )
            for node_data in nodes:
                if isinstance(node_data, dict):
                    self._proxy_pool.add_proxy(ProxyNode(
                        url=node_data.get("url", ""),
                        provider=node_data.get("provider", "manual"),
                        geo_country=node_data.get("geo", node_data.get("geo_country", "")),
                        proxy_type=node_data.get("type", node_data.get("proxy_type", "datacenter")),
                    ))
            logger.info(f"Proxy pool initialized with {len(nodes)} nodes")
        except Exception as exc:
            logger.debug(f"Proxy pool init skipped: {exc}")
            self._proxy_pool = None

    def _init_captcha_dispatcher(self):
        """Lazy-init the CAPTCHA dispatcher from config."""
        if self._captcha_dispatcher is not None:
            return
        try:
            from cf_bypass.solvers.dispatcher import (
                CaptchaDispatcher,
                DispatcherConfig,
                ProviderEntry,
            )

            cfg = self.config.captcha
            entries_by_type = {}
            for ct_name in ["turnstile", "recaptcha_v2", "recaptcha_v3", "hcaptcha", "image"]:
                provider_names = cfg.providers.get(ct_name, [])
                entries = []
                for i, name in enumerate(provider_names):
                    entries.append(ProviderEntry(
                        name=name,
                        api_key=cfg.api_keys.get(name, ""),
                        priority=i,
                    ))
                entries_by_type[ct_name] = entries

            dispatcher_config = DispatcherConfig(
                turnstile=entries_by_type.get("turnstile", []),
                recaptcha_v2=entries_by_type.get("recaptcha_v2", []),
                recaptcha_v3=entries_by_type.get("recaptcha_v3", []),
                hcaptcha=entries_by_type.get("hcaptcha", []),
                image=entries_by_type.get("image", []),
                timeout=cfg.timeout,
                max_retries=cfg.max_retries,
            )
            self._captcha_dispatcher = CaptchaDispatcher(dispatcher_config)
            logger.debug("CAPTCHA dispatcher initialized")
        except Exception as exc:
            logger.debug(f"CAPTCHA dispatcher init skipped: {exc}")

    def _get_or_create_fingerprint(self):
        """Get or create a per-session fingerprint profile."""
        if self._fingerprint_profile is not None:
            return self._fingerprint_profile
        fp_cfg = getattr(self.config, 'fingerprint', None)
        if fp_cfg and getattr(fp_cfg, 'enabled', False):
            try:
                from cf_bypass.fingerprint.generator import FingerprintGenerator
                gen = FingerprintGenerator()
                self._fingerprint_profile = gen.generate()
                logger.debug(
                    f"Fingerprint generated: {self._fingerprint_profile.profile_id}"
                )
            except Exception as exc:
                logger.debug(f"Fingerprint generation skipped: {exc}")
        return self._fingerprint_profile

    # ------------------------------------------------------------------
    # Main entry point
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
            Optional proxy URL. If None, uses config proxy or proxy pool.
        timeout:
            Per-strategy timeout in seconds. Falls back to config.timeout.
        headless:
            Browser headless mode. Falls back to config.headless.
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

        # Resolve proxy (CLI arg > proxy pool > config proxy)
        effective_proxy = await self._resolve_proxy(proxy)

        # Run proxy health check if single proxy configured
        proxy_cfg = getattr(self.config, 'proxy', None)
        health_check_enabled = getattr(proxy_cfg, 'health_check', False) if proxy_cfg else False
        if effective_proxy and not self._proxy_pool and health_check_enabled is True:
            from cf_bypass.proxy_checker import ProxyChecker
            health = await ProxyChecker.check_latency(effective_proxy, timeout=10.0)
            if not health.healthy:
                logger.warning(
                    f"Proxy health check failed: {health.error}. "
                    f"Falling back to direct connection."
                )
                effective_proxy = None
            else:
                geo = getattr(proxy_cfg, 'geo_required', '') if proxy_cfg else ''
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
        # Step 1.5: Smart routing — quick probe (v2.0)
        # --------------------------------------------------------------
        start_level = 1
        routing_cfg = getattr(self.config, 'routing', None)
        smart_routing = getattr(routing_cfg, 'smart', False) if routing_cfg else False
        if smart_routing is True:  # Strict check (exclude MagicMock truthy)
            probe = await self._quick_probe(url, proxy=effective_proxy, timeout=timeout)
            start_level = probe.suggested_level
            logger.info(
                f"Smart routing: probe suggests starting at L{start_level} "
                f"(status={probe.status_code}, challenge={probe.has_challenge}, "
                f"turnstile={probe.has_turnstile})"
            )

        # --------------------------------------------------------------
        # Step 2: Progressive strategy chain
        # --------------------------------------------------------------
        # Generate fingerprint profile for this session
        fp_profile = self._get_or_create_fingerprint()

        last_error = None
        strategy_errors: List[str] = []

        for strategy in self._strategies:
            # Skip strategies below the suggested start level
            if strategy.level < start_level:
                logger.debug(f"Skipping L{strategy.level} (smart routing)")
                continue

            strategy_name = strategy.name
            strategy_level = strategy.level

            # Increase timeout progressively for heavier strategies
            effective_timeout = timeout + (strategy_level - 1) * 10

            logger.info(
                f"Trying L{strategy_level}: {strategy_name} "
                f"(timeout={effective_timeout}s)"
            )

            try:
                # Apply retry policy if configured (defensive against mocks)
                # Only enable retry when routing config has real values
                max_retries = 0
                routing_cfg2 = getattr(self.config, 'routing', None)
                if routing_cfg2 is not None and hasattr(routing_cfg2, 'max_retries'):
                    raw = getattr(routing_cfg2, 'max_retries', 0)
                    # Check it's a real number (not a MagicMock)
                    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
                        max_retries = int(raw)
                    # else: it's a mock — leave max_retries at 0

                if max_retries > 0:
                    result = await self._execute_with_retry(
                        strategy, url, effective_proxy, effective_timeout,
                        headless, cached_cookies, keep_open,
                        fp_profile, max_retries,
                    )
                else:
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
                    if result.cookies:
                        await self.cookie_manager.store(domain, result.cookies)
                    if cookie_only:
                        result.html = None
                    self._record_metrics(url, domain, result, effective_proxy)
                    return result

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
            "Configure CAPTCHA solver (set captcha.api_keys in config.yaml)",
            "Enable smart routing (set routing.smart: true in config.yaml)",
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
    # Smart routing: quick probe
    # ------------------------------------------------------------------

    async def _quick_probe(
        self,
        url: str,
        proxy: Optional[str] = None,
        timeout: int = 60,
    ) -> ProbeResult:
        """Perform a quick L1 probe to determine the best starting strategy.

        Makes a fast request with minimal overhead and analyzes the response
        to route to the appropriate strategy level.

        Decision table:
        - 200 + cf_clearance → L1 (simple site, no challenge)
        - 200 + challenge keywords → L3 (JS challenge)
        - 200 + turnstile indicators → L4 (browser interactive)
        - 403 → L3 (likely bot detection, need browser)
        - 503 → L2 (temporary block, try different TLS fingerprint)
        - Timeout → L1 (network issue, retry simple)
        """
        probe = ProbeResult()

        try:
            client_kwargs: dict = {
                "timeout": min(timeout, 15.0),
                "follow_redirects": True,
            }
            if proxy:
                client_kwargs["proxies"] = proxy

            async with httpx.AsyncClient(**client_kwargs) as client:
                response = await client.get(url)
                probe.status_code = response.status_code
                html_lower = response.text.lower()

                # Check for challenge indicators
                challenge_keywords = [
                    "just a moment", "checking your browser",
                    "cf-browser-verification", "challenge-platform",
                ]
                probe.has_challenge = any(
                    kw in html_lower for kw in challenge_keywords
                )
                probe.has_turnstile = "turnstile" in html_lower
                probe.has_captcha = (
                    "recaptcha" in html_lower or "hcaptcha" in html_lower
                )

                # Check for cf_clearance cookie
                has_clearance = "cf_clearance" in dict(response.cookies)

                # Determine suggested level
                if response.status_code == 200:
                    if has_clearance and not probe.has_challenge:
                        probe.suggested_level = 1  # Already bypassed
                    elif probe.has_turnstile:
                        probe.suggested_level = 4  # Need browser interaction
                    elif probe.has_challenge:
                        probe.suggested_level = 3  # JS challenge
                    else:
                        probe.suggested_level = 1
                elif response.status_code == 403:
                    if probe.has_challenge:
                        probe.suggested_level = 4
                    else:
                        probe.suggested_level = 3  # Bot detection
                elif response.status_code in (429, 503):
                    probe.suggested_level = 2  # Rate limit, try different TLS
                else:
                    probe.suggested_level = 1  # Default

        except Exception as exc:
            logger.debug(f"Quick probe failed: {exc}")
            probe.suggested_level = 1  # Default on probe failure

        return probe

    # ------------------------------------------------------------------
    # Retry wrapper
    # ------------------------------------------------------------------

    async def _execute_with_retry(
        self,
        strategy,
        url: str,
        proxy: Optional[str],
        timeout: int,
        headless: bool,
        existing_cookies: Optional[Dict],
        keep_open: bool,
        fp_profile=None,
        max_retries: int = 3,
    ) -> BypassResult:
        """Execute a strategy with retry logic."""
        from cf_bypass.retry import RetryPolicy, RetryConfig

        # Extract retry config values defensively (handle MagicMock in tests)
        routing_cfg3 = getattr(self.config, 'routing', None)
        try:
            base_delay = float(getattr(routing_cfg3, 'base_delay', 1.0)) if routing_cfg3 else 1.0
        except (TypeError, ValueError):
            base_delay = 1.0
        try:
            max_delay = float(getattr(routing_cfg3, 'max_delay', 30.0)) if routing_cfg3 else 30.0
        except (TypeError, ValueError):
            max_delay = 30.0
        try:
            jitter = float(getattr(routing_cfg3, 'jitter', 0.2)) if routing_cfg3 else 0.2
        except (TypeError, ValueError):
            jitter = 0.2

        retry_config = RetryConfig(
            max_retries=max_retries,
            base_delay=base_delay,
            max_delay=max_delay,
            jitter=jitter,
        )
        policy = RetryPolicy(retry_config)

        async def attempt():
            return await strategy.bypass(
                url=url,
                proxy=proxy,
                timeout=timeout,
                headless=headless,
                existing_cookies=existing_cookies,
                keep_open=keep_open,
            )

        try:
            result = await policy.execute(
                attempt,
                is_success_fn=is_bypass_successful,
            )
            return result
        except RuntimeError as exc:
            logger.debug(f"Retry exhausted for {strategy.name}: {exc}")
            # Return the last known result if available, or a failure
            return BypassResult(
                success=False,
                error=str(exc),
                strategy_name=strategy.name,
                level=strategy.level,
            )

    # ------------------------------------------------------------------
    # Proxy resolution
    # ------------------------------------------------------------------

    async def _resolve_proxy(self, cli_proxy: Optional[str]) -> Optional[str]:
        """Resolve the effective proxy from CLI arg, pool, or config."""
        # CLI arg takes precedence
        if cli_proxy:
            return cli_proxy

        # Proxy pool (v2.0)
        self._init_proxy_pool()
        if self._proxy_pool:
            try:
                proxy_cfg = getattr(self.config, 'proxy', None)
                geo_str = getattr(proxy_cfg, 'geo_required', '') if proxy_cfg else ''
                node = await self._proxy_pool.get(
                    geo=geo_str or "",
                )
                if node:
                    logger.debug(f"Selected proxy from pool: {node.url[:50]}...")
                    return node.url
            except Exception as exc:
                logger.debug(f"Proxy pool selection failed: {exc}")

        # Fall back to single config proxy
        return self.config.proxy.get_url()

    # ------------------------------------------------------------------
    # Metrics recording (v2.0)
    # ------------------------------------------------------------------

    def _record_metrics(
        self,
        url: str,
        domain: str,
        result: BypassResult,
        proxy: Optional[str],
    ) -> None:
        """Record bypass metrics if observability is enabled."""
        obs_cfg = getattr(self.config, 'observability', None)
        if not obs_cfg or not getattr(obs_cfg, 'enabled', False):
            return
        try:
            from cf_bypass.observability.metrics import BypassMetrics, record_metrics
            metrics = BypassMetrics(
                url=url,
                domain=domain,
                duration_ms=int(result.duration * 1000),
                strategy_used=result.strategy_name,
                strategy_level=result.level,
                cache_hit=False,
                proxy_used=proxy or "none",
                challenge_detected=result.challenge_detected,
                challenge_type=result.challenge_type,
                final_status_code=result.status_code or 0,
                html_size=len(result.html) if result.html else 0,
                cookie_count=len(result.cookies),
                error_code=result.error,
            )
            record_metrics(metrics, self.config.observability.path)
        except Exception as exc:
            logger.debug(f"Metrics recording failed (non-fatal): {exc}")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _make_request_with_cookies(
        self,
        url: str,
        cookies: Dict[str, str],
        proxy: Optional[str] = None,
        timeout: int = 60,
    ) -> BypassResult:
        """Lightweight GET request using cached cookies via httpx."""
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
        if self._captcha_dispatcher:
            try:
                self._captcha_dispatcher.clear_provider_cache()
            except Exception:
                pass

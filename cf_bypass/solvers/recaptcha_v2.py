"""Google reCAPTCHA v2 solver.

Supports both image and audio challenge paths, with provider-based
solving via the CaptchaDispatcher.

Detection: looks for g-recaptcha divs, grecaptcha.render() calls,
and the reCAPTCHA v2 API script.
"""

import time
import re
from typing import Optional

from cf_bypass.solvers.base import BaseSolver, SolverResult
from cf_bypass.logging_config import get_logger

logger = get_logger("solvers.recaptcha_v2")

# ---------------------------------------------------------------------------
# reCAPTCHA v2 detection patterns
# ---------------------------------------------------------------------------

RECAPTCHA_V2_SITEKEY_PATTERNS = [
    re.compile(r'data-sitekey\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE),
    re.compile(r'grecaptcha\.render\s*\(\s*["\']([^"\']+)["\']', re.IGNORECASE),
    # Widget div
    re.compile(
        r'<div[^>]*class\s*=\s*["\'][^"\']*g-recaptcha[^"\']*["\'][^>]*>',
        re.IGNORECASE,
    ),
]

RECAPTCHA_V2_INDICATORS = [
    "recaptcha/api2",
    "g-recaptcha",
    "grecaptcha.render",
    "google.com/recaptcha",
]

# JS to extract the reCAPTCHA sitekey from the DOM
RECAPTCHA_SITEKEY_JS = """
(() => {
    const el = document.querySelector('.g-recaptcha, [data-sitekey]');
    if (!el) return null;
    return el.getAttribute('data-sitekey') || el.dataset.sitekey || null;
})()
"""

# JS to check if reCAPTCHA is solved (token present)
RECAPTCHA_TOKEN_JS = """
(() => {
    const el = document.getElementById('g-recaptcha-response');
    return el ? el.value || null : null;
})()
"""

# JS to inject a token into the reCAPTCHA response field
RECAPTCHA_INJECT_JS = """
((token) => {
    // Set the hidden textarea
    const textarea = document.getElementById('g-recaptcha-response');
    if (textarea) {
        textarea.innerHTML = token;
        textarea.value = token;
    }
    // Call the callback if present
    if (window.___grecaptcha_cfg && window.___grecaptcha_cfg.clients) {
        Object.keys(window.___grecaptcha_cfg.clients).forEach(id => {
            const client = window.___grecaptcha_cfg.clients[id];
            if (client && client.callback) {
                try { client.callback(token); } catch(e) {}
            }
        });
    }
    // Try calling global callbacks
    if (typeof window.onRecaptchaSuccess === 'function') {
        window.onRecaptchaSuccess(token);
    }
})(arguments[0])
"""


class RecaptchaV2Solver(BaseSolver):
    """Solve Google reCAPTCHA v2 challenges.

    Supports provider-based solving (capsolver, 2captcha) with automatic
    token injection into the page DOM.

    Usage::

        solver = RecaptchaV2Solver()
        result = await solver.solve(page, sitekey, url, timeout=120)
        if result.success:
            await solver.inject_token(page, result.token)
    """

    def __init__(self, dispatcher=None):
        """Initialize with an optional CaptchaDispatcher.

        Args:
            dispatcher: CaptchaDispatcher instance for provider routing.
                        If None, provider-based solving is unavailable.
        """
        self.dispatcher = dispatcher

    @property
    def name(self) -> str:
        return "recaptcha_v2"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def solve(
        self,
        page_or_html,
        sitekey: str,
        url: str,
        timeout: int = 60,
    ) -> SolverResult:
        """Solve a reCAPTCHA v2 challenge.

        If a dispatcher is configured, routes through providers.
        Otherwise falls back to browser-injection observation.

        Args:
            page_or_html: Browser page object or HTML string.
            sitekey: The reCAPTCHA sitekey.
            url: Page URL.
            timeout: Maximum wait time in seconds.

        Returns:
            SolverResult with the g-recaptcha-response token.
        """
        start = time.time()

        # Try dispatcher first (provider-based solving)
        if self.dispatcher:
            try:
                from cf_bypass.solvers.dispatcher import CaptchaType
                result = await self.dispatcher.solve(
                    page_or_html,
                    CaptchaType.RECAPTCHA_V2,
                    sitekey=sitekey,
                    url=url,
                    timeout=timeout,
                )
                if result.success:
                    return result
                logger.debug(f"Dispatcher failed for reCAPTCHA v2: {result.error}")
            except Exception as exc:
                logger.debug(f"Dispatcher error: {exc}")

        # Fallback: if page object available, try observation mode
        if hasattr(page_or_html, "evaluate"):
            return await self._observe_token(page_or_html, timeout, start)

        return SolverResult(
            success=False,
            duration=time.time() - start,
            error="No dispatcher configured and no browser page available",
        )

    async def solve_with_provider(
        self,
        sitekey: str,
        page_url: str,
        provider_name: str = "capsolver",
        api_key: str = "",
        timeout: int = 120,
    ) -> SolverResult:
        """Solve using a specific provider directly.

        Convenience method when no full dispatcher is needed.
        """
        from cf_bypass.solvers.dispatcher import (
            CaptchaType,
            DispatcherConfig,
            ProviderEntry,
            CaptchaDispatcher,
        )

        config = DispatcherConfig(
            recaptcha_v2=[
                ProviderEntry(name=provider_name, api_key=api_key, priority=0),
            ],
            timeout=timeout,
        )
        dispatcher = CaptchaDispatcher(config)

        result = await dispatcher.solve(
            "", CaptchaType.RECAPTCHA_V2,
            sitekey=sitekey,
            url=page_url,
            timeout=timeout,
        )

        dispatcher.clear_provider_cache()
        return result

    async def inject_token(self, page, token: str) -> bool:
        """Inject a solved reCAPTCHA token into the page.

        After calling this, the page should process the token and
        submit the form / trigger the callback.

        Returns True if injection succeeded.
        """
        try:
            await page.evaluate(RECAPTCHA_INJECT_JS, token)
            logger.info("reCAPTCHA v2 token injected into page")
            return True
        except Exception as exc:
            logger.warning(f"reCAPTCHA token injection failed: {exc}")
            return False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _observe_token(
        self,
        page,
        timeout: int,
        start: float,
    ) -> SolverResult:
        """Poll the page for a reCAPTCHA token to appear (observation mode)."""
        deadline = start + timeout
        interval = 1.0

        while time.time() < deadline:
            try:
                token = await page.evaluate(RECAPTCHA_TOKEN_JS)
            except Exception:
                await self._sleep(interval)
                interval = min(interval * 1.5, 5.0)
                continue

            if token:
                duration = time.time() - start
                return SolverResult(
                    token=token,
                    success=True,
                    duration=round(duration, 2),
                )

            await self._sleep(interval)
            interval = min(interval * 1.5, 5.0)

        return SolverResult(
            success=False,
            duration=time.time() - start,
            error="reCAPTCHA token did not appear within timeout",
        )

    @staticmethod
    async def _sleep(seconds: float) -> None:
        import asyncio
        await asyncio.sleep(seconds)

    # ------------------------------------------------------------------
    # Static detection helpers
    # ------------------------------------------------------------------

    @staticmethod
    def extract_sitekey(html: str) -> Optional[str]:
        """Extract reCAPTCHA v2 sitekey from HTML."""
        if not html:
            return None

        for pattern in RECAPTCHA_V2_SITEKEY_PATTERNS[:2]:
            m = pattern.search(html)
            if m and m.lastindex and m.lastindex >= 1:
                return m.group(1)
        return None

    @staticmethod
    def is_present(html: str) -> bool:
        """Check if reCAPTCHA v2 is present in the page."""
        if not html:
            return False
        html_lower = html.lower()
        return any(ind in html_lower for ind in RECAPTCHA_V2_INDICATORS)

    @staticmethod
    def is_invisible(html: str) -> bool:
        """Check if this is an invisible reCAPTCHA (v2 checkbox is invisible)."""
        if not html:
            return False
        return "invisible" in html.lower() and "recaptcha" in html.lower()

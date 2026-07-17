"""hCaptcha solver.

hCaptcha is similar to reCAPTCHA v2 in structure (checkbox → image grid),
but has its own API, sitekey format, and response field name.

API support: Capsolver, 2Captcha both provide hCaptcha solving.
"""

import time
import re
from typing import Optional

from cf_bypass.solvers.base import BaseSolver, SolverResult
from cf_bypass.logging_config import get_logger

logger = get_logger("solvers.hcaptcha")

# ---------------------------------------------------------------------------
# hCaptcha detection
# ---------------------------------------------------------------------------

HCAPTCHA_SITEKEY_PATTERNS = [
    re.compile(r'data-sitekey\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE),
    re.compile(r'sitekey\s*:\s*["\']([^"\']+)["\']', re.IGNORECASE),
    re.compile(r'hcaptcha\.render\s*\(\s*["\']([^"\']+)["\']', re.IGNORECASE),
]

HCAPTCHA_INDICATORS = [
    "hcaptcha.com",
    "h-captcha",
    "hcaptcha.render",
    "hcaptchaResponse",
    "data-hcaptcha-widget-id",
]

# JS helpers
HCAPTCHA_SITEKEY_JS = """
(() => {
    const el = document.querySelector('.h-captcha, [data-sitekey]');
    if (!el) return null;
    return el.getAttribute('data-sitekey') || el.dataset.sitekey || null;
})()
"""

HCAPTCHA_TOKEN_JS = """
(() => {
    const el = document.querySelector('[name="h-captcha-response"]');
    return el ? el.value || null : null;
})()
"""

HCAPTCHA_INJECT_JS = """
((token) => {
    const textarea = document.querySelector('[name="h-captcha-response"]');
    if (textarea) {
        textarea.value = token;
    }
    // Trigger hcaptcha callback
    if (window.hcaptcha && typeof window.hcaptcha.setResp === 'function') {
        try { window.hcaptcha.setResp(token); } catch(e) {}
    }
    // Call site-level callbacks
    if (typeof window.onHcaptchaSuccess === 'function') {
        window.onHcaptchaSuccess(token);
    }
})(arguments[0])
"""


class HCaptchaSolver(BaseSolver):
    """Solve hCaptcha challenges via provider APIs.

    Usage::

        solver = HCaptchaSolver()
        result = await solver.solve(page, sitekey, url)
        if result.success:
            await solver.inject_token(page, result.token)
    """

    def __init__(self, dispatcher=None):
        self.dispatcher = dispatcher

    @property
    def name(self) -> str:
        return "hcaptcha"

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
        """Solve an hCaptcha challenge.

        Routes through the dispatcher if configured; otherwise falls
        back to DOM observation on a live page.
        """
        start = time.time()

        if self.dispatcher:
            try:
                from cf_bypass.solvers.dispatcher import CaptchaType
                result = await self.dispatcher.solve(
                    page_or_html,
                    CaptchaType.HCAPTCHA,
                    sitekey=sitekey,
                    url=url,
                    timeout=timeout,
                )
                if result.success:
                    return result
                logger.debug(f"Dispatcher failed for hCaptcha: {result.error}")
            except Exception as exc:
                logger.debug(f"Dispatcher error: {exc}")

        # Fallback: observer mode
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
        """Solve hCaptcha using a specific provider directly."""
        from cf_bypass.solvers.dispatcher import (
            CaptchaType,
            DispatcherConfig,
            ProviderEntry,
            CaptchaDispatcher,
        )

        config = DispatcherConfig(
            hcaptcha=[
                ProviderEntry(name=provider_name, api_key=api_key, priority=0),
            ],
            timeout=timeout,
        )
        dispatcher = CaptchaDispatcher(config)

        result = await dispatcher.solve(
            "", CaptchaType.HCAPTCHA,
            sitekey=sitekey,
            url=page_url,
            timeout=timeout,
        )
        dispatcher.clear_provider_cache()
        return result

    async def inject_token(self, page, token: str) -> bool:
        """Inject a solved hCaptcha token into the page DOM."""
        try:
            await page.evaluate(HCAPTCHA_INJECT_JS, token)
            logger.info("hCaptcha token injected into page")
            return True
        except Exception as exc:
            logger.warning(f"hCaptcha token injection failed: {exc}")
            return False

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _observe_token(self, page, timeout: int, start: float) -> SolverResult:
        """Poll for h-captcha-response to appear."""
        deadline = start + timeout
        interval = 1.0

        while time.time() < deadline:
            try:
                token = await page.evaluate(HCAPTCHA_TOKEN_JS)
            except Exception:
                await self._sleep(interval)
                interval = min(interval * 1.5, 5.0)
                continue

            if token:
                return SolverResult(
                    token=token,
                    success=True,
                    duration=round(time.time() - start, 2),
                )

            await self._sleep(interval)
            interval = min(interval * 1.5, 5.0)

        return SolverResult(
            success=False,
            duration=time.time() - start,
            error="hCaptcha token did not appear within timeout",
        )

    @staticmethod
    async def _sleep(seconds: float) -> None:
        import asyncio
        await asyncio.sleep(seconds)

    # ------------------------------------------------------------------
    # Static helpers
    # ------------------------------------------------------------------

    @staticmethod
    def extract_sitekey(html: str) -> Optional[str]:
        """Extract hCaptcha sitekey from HTML."""
        if not html:
            return None
        for pattern in HCAPTCHA_SITEKEY_PATTERNS:
            m = pattern.search(html)
            if m and m.lastindex and m.lastindex >= 1:
                return m.group(1)
        return None

    @staticmethod
    def is_present(html: str) -> bool:
        """Check if hCaptcha is present."""
        if not html:
            return False
        html_lower = html.lower()
        return any(ind in html_lower for ind in HCAPTCHA_INDICATORS)

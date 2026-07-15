"""Cloudflare Turnstile solver with capsolver/2captcha API integration.

Supports two resolution modes:

1. **API mode** — submit sitekey + page URL to a captcha service,
   poll for the token, and return it to the caller.

2. **Browser injection mode** — when a live browser page (nodriver
   or Playwright) is available, inject JavaScript to intercept the
   Turnstile callback and wait for the token to appear automatically.
"""

import re
import time
from typing import Optional

import httpx

from cf_bypass.solvers.base import BaseSolver, SolverResult
from cf_bypass.logging_config import get_logger

logger = get_logger("solvers.turnstile")

# ---------------------------------------------------------------------------
# Capsolver API constants
# ---------------------------------------------------------------------------
CAPSOLVER_CREATE_TASK = "https://api.capsolver.com/createTask"
CAPSOLVER_GET_RESULT = "https://api.capsolver.com/getTaskResult"
CAPSOLVER_POLL_INTERVAL = 2.0  # seconds between status checks


# ---------------------------------------------------------------------------
# Turnstile detection helpers
# ---------------------------------------------------------------------------

TURNSTILE_SITEKEY_PATTERNS = [
    # Standard Cloudflare Turnstile widget
    re.compile(r'data-sitekey\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE),
    # JavaScript inline: sitekey: '...'
    re.compile(r'sitekey\s*:\s*["\']([^"\']+)["\']', re.IGNORECASE),
    # cf-turnstile div
    re.compile(
        r'<div[^>]*class\s*=\s*["\'][^"\']*cf-turnstile[^"\']*["\'][^>]*>',
        re.IGNORECASE,
    ),
    # iframe src with challenges.cloudflare.com
    re.compile(
        r'src\s*=\s*["\']https?://challenges\.cloudflare\.com[^"\']*["\']',
        re.IGNORECASE,
    ),
]

# JS to detect if Turnstile is present in the DOM
TURNSTILE_DETECT_JS = """
(() => {
    const widget = document.querySelector('.cf-turnstile, [data-sitekey]');
    if (!widget) return null;
    return widget.getAttribute('data-sitekey') || widget.dataset.sitekey || null;
})()
"""

# JS to poll for the turnstile token after the challenge is solved
TURNSTILE_TOKEN_POLL_JS = """
(() => {
    const el = document.querySelector('[name="cf-turnstile-response"]');
    return el ? el.value || null : null;
})()
"""


class TurnstileSolver(BaseSolver):
    """Solve Cloudflare Turnstile challenges via API or browser injection.

    Usage with API key::

        solver = TurnstileSolver(api_key="CAP-...", service="capsolver")
        result = await solver.solve_via_api(sitekey, page_url, timeout=120)

    Usage with browser page::

        solver = TurnstileSolver()
        result = await solver.solve_via_injection(page, sitekey, timeout=60)
    """

    def __init__(
        self,
        api_key: str = "",
        service: str = "capsolver",
    ):
        self.api_key = api_key
        self.service = service  # "capsolver" | "2captcha"

    @property
    def name(self) -> str:
        return "turnstile"

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
        """Solve a Turnstile challenge.

        If *page_or_html* is a browser page object (has an ``evaluate``
        method), uses injection mode.  Otherwise falls back to API mode
        if an API key is configured.
        """
        # Prefer injection mode when we have a live page
        if hasattr(page_or_html, "evaluate"):
            return await self.solve_via_injection(
                page_or_html, sitekey, timeout=timeout
            )

        # Fallback: API mode (requires api_key)
        if self.api_key:
            return await self.solve_via_api(sitekey, url, timeout=timeout)

        return SolverResult(
            success=False,
            error="No browser page available and no API key configured",
        )

    async def solve_via_api(
        self,
        sitekey: str,
        page_url: str,
        timeout: int = 120,
    ) -> SolverResult:
        """Submit to a captcha-solving service and poll for the token.

        Currently supports Capsolver. 2captcha support can be added
        by implementing the same createTask / getTaskResult pattern.
        """
        if not self.api_key:
            return SolverResult(
                success=False,
                error="No API key configured for captcha service",
            )

        if self.service not in ("capsolver", "2captcha"):
            return SolverResult(
                success=False,
                error=f"Unknown captcha service: {self.service}",
            )

        start = time.time()

        try:
            task_id = await self._create_task(sitekey, page_url)
            if not task_id:
                return SolverResult(
                    success=False,
                    duration=time.time() - start,
                    error="Failed to create captcha task",
                )

            logger.info(
                f"Turnstile task created: {task_id[:20]}... "
                f"(service={self.service})"
            )

            token = await self._poll_task(task_id, timeout=timeout)
            duration = time.time() - start

            if token:
                return SolverResult(
                    token=token,
                    success=True,
                    duration=round(duration, 2),
                )

            return SolverResult(
                success=False,
                duration=round(duration, 2),
                error="Captcha solving timed out",
            )

        except Exception as exc:
            logger.debug(f"Turnstile API solve error: {exc}")
            return SolverResult(
                success=False,
                duration=time.time() - start,
                error=str(exc),
            )

    async def solve_via_injection(
        self,
        page,
        sitekey: str,
        timeout: int = 60,
    ) -> SolverResult:
        """Inject JS to wait for the Turnstile token to appear in the DOM.

        This works when the page includes a Turnstile widget that resolves
        automatically (e.g. via non-interactive / managed mode).  The JS
        polls ``[name="cf-turnstile-response"]`` until a non-empty value
        appears or the timeout expires.
        """
        start = time.time()
        deadline = start + timeout
        interval = 1.0  # seconds between polls

        logger.info(
            f"Waiting for Turnstile token via injection "
            f"(sitekey={sitekey[:20]}..., timeout={timeout}s)"
        )

        while time.time() < deadline:
            try:
                token = await page.evaluate(TURNSTILE_TOKEN_POLL_JS)
            except Exception:
                # Page may be navigating — wait and retry
                if hasattr(page, "sleep"):
                    await page.sleep(interval)
                else:
                    import asyncio
                    await asyncio.sleep(interval)
                interval = min(interval * 1.5, 5.0)
                continue

            if token:
                duration = time.time() - start
                logger.info(f"Turnstile token obtained in {duration:.1f}s")
                return SolverResult(
                    token=token,
                    success=True,
                    duration=round(duration, 2),
                )

            # Wait before next poll
            if hasattr(page, "sleep"):
                await page.sleep(interval)
            else:
                import asyncio
                await asyncio.sleep(interval)
            interval = min(interval * 1.5, 5.0)

        return SolverResult(
            success=False,
            duration=time.time() - start,
            error="Turnstile token did not appear within timeout",
        )

    # ------------------------------------------------------------------
    # Capsolver API helpers
    # ------------------------------------------------------------------

    async def _create_task(self, sitekey: str, page_url: str) -> Optional[str]:
        """Submit a Turnstile task to Capsolver and return the task ID."""
        payload = {
            "clientKey": self.api_key,
            "task": {
                "type": "AntiTurnstileTaskProxyLess",
                "websiteURL": page_url,
                "websiteKey": sitekey,
            },
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(CAPSOLVER_CREATE_TASK, json=payload)
                data = resp.json()

                if data.get("errorId") != 0:
                    error_desc = data.get("errorDescription", "Unknown error")
                    logger.warning(f"Capsolver createTask error: {error_desc}")
                    return None

                return data.get("taskId")

        except Exception as exc:
            logger.warning(f"Capsolver createTask request failed: {exc}")
            return None

    async def _poll_task(
        self,
        task_id: str,
        timeout: int = 120,
    ) -> Optional[str]:
        """Poll Capsolver until the task completes or times out."""
        deadline = time.time() + timeout

        while time.time() < deadline:
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.post(CAPSOLVER_GET_RESULT, json={
                        "clientKey": self.api_key,
                        "taskId": task_id,
                    })
                    data = resp.json()

                    if data.get("errorId") != 0:
                        logger.warning(
                            f"Capsolver getResult error: "
                            f"{data.get('errorDescription', 'Unknown')}"
                        )
                        return None

                    status = data.get("status", "")
                    if status == "ready":
                        solution = data.get("solution", {})
                        token = solution.get("token") or solution.get(
                            "cf_clearance"
                        )
                        if token:
                            return token

                    # Still processing — wait before next poll
                    await self._async_sleep(CAPSOLVER_POLL_INTERVAL)

            except Exception as exc:
                logger.debug(f"Capsolver poll error (will retry): {exc}")
                await self._async_sleep(CAPSOLVER_POLL_INTERVAL)

        return None

    @staticmethod
    async def _async_sleep(seconds: float) -> None:
        """Async sleep compatible with any event loop."""
        import asyncio
        await asyncio.sleep(seconds)

    # ------------------------------------------------------------------
    # Static helpers
    # ------------------------------------------------------------------

    @staticmethod
    def extract_sitekey(html: str) -> Optional[str]:
        """Extract the Turnstile sitekey from an HTML string.

        Returns the first matching sitekey, or None if no Turnstile
        widget is found.
        """
        if not html:
            return None

        for pattern in TURNSTILE_SITEKEY_PATTERNS[:2]:  # key-value patterns
            m = pattern.search(html)
            if m:
                return m.group(1)

        # Fallback: detect widget presence without extracting key
        for pattern in TURNSTILE_SITEKEY_PATTERNS[2:]:
            if pattern.search(html):
                return "__detected__"  # widget present but sitekey not found

        return None

    @staticmethod
    def is_turnstile_present(html: str) -> bool:
        """Return True if the HTML contains a Turnstile widget."""
        return TurnstileSolver.extract_sitekey(html) is not None

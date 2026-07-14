"""Level 3: playwright + playwright-stealth — full browser automation.

Launches a real Chromium browser, applies stealth patches to hide
automation signatures (navigator.webdriver, CDP Runtime.events, etc.),
navigates to the target page, waits for challenges to resolve, and
extracts the resulting cookies.

This is the primary strategy for Cloudflare Managed Challenge.
"""

import time
from typing import Optional, Dict
from urllib.parse import urlparse

from playwright.async_api import async_playwright
from playwright_stealth import Stealth

from cf_bypass.strategies.base import BaseStrategy, BypassResult
from cf_bypass.logging_config import get_logger

logger = get_logger("strategies.playwright")

CHROME_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


async def _safe_content(page, retries: int = 3, wait_ms: int = 2000) -> Optional[str]:
    """Call ``page.content()`` safely, retrying if the page is navigating.

    Playwright raises ``Error`` when ``content()`` is called while a
    navigation is in progress.  This helper catches that specific error,
    waits, and retries up to *retries* times.

    Returns the HTML string on success, or ``None`` if all retries fail.
    """
    for attempt in range(retries + 1):
        try:
            return await page.content()
        except Exception as e:
            msg = str(e)
            # Only retry on navigation-in-progress errors
            if "navigating" in msg.lower() or "changing the content" in msg.lower():
                if attempt < retries:
                    logger.debug(
                        f"page.content() retry {attempt + 1}/{retries}: "
                        f"page still navigating, waiting {wait_ms}ms"
                    )
                    await page.wait_for_timeout(wait_ms)
                    continue
            # Not a navigation error, or retries exhausted
            if attempt >= retries:
                logger.warning(f"page.content() failed after {retries} retries: {e}")
    return None


class Level3Playwright(BaseStrategy):
    """Level 3: playwright + stealth patches.

    Launches a headed (or headless) Chromium browser, injects anti-detection
    scripts via playwright-stealth, navigates to the target, and waits for
    any Cloudflare challenges to resolve.
    """

    @property
    def name(self) -> str:
        return "playwright"

    @property
    def level(self) -> int:
        return 3

    async def bypass(
        self,
        url: str,
        proxy: Optional[str] = None,
        timeout: int = 60,
        headless: bool = False,
        existing_cookies: Optional[Dict[str, str]] = None,
        keep_open: bool = False,
    ) -> BypassResult:
        """Launch browser, navigate, wait for challenge, extract cookies."""
        start = time.time()
        browser = None
        self._keep_open = keep_open

        try:
            async with async_playwright() as p:
                launch_kwargs: dict = {
                    "headless": headless,
                    "args": [
                        "--no-sandbox",
                        "--disable-blink-features=AutomationControlled",
                        "--disable-dev-shm-usage",
                    ],
                }
                if proxy:
                    launch_kwargs["proxy"] = {"server": proxy}

                browser = await p.chromium.launch(**launch_kwargs)

                context_kwargs: dict = {
                    "viewport": {"width": 1920, "height": 1080},
                    "user_agent": CHROME_USER_AGENT,
                    "locale": "en-US",
                    "timezone_id": "America/New_York",
                }

                context = await browser.new_context(**context_kwargs)
                page = await context.new_page()

                # Apply playwright-stealth anti-detection patches
                stealth = Stealth()
                await stealth.apply_stealth_async(page)

                # Inject pre-existing cookies if available
                if existing_cookies:
                    domain = urlparse(url).netloc
                    cookie_objs = [
                        {
                            "name": k,
                            "value": v,
                            "domain": domain,
                            "path": "/",
                        }
                        for k, v in existing_cookies.items()
                    ]
                    await context.add_cookies(cookie_objs)

                # Navigate to target
                logger.debug(f"Navigating to {url}")
                response = await page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=timeout * 1000,
                )

                # Wait for post-load challenge resolution.
                # Cloudflare often triggers redirects / JS execution after
                # initial DOM load, so we wait for network idle with timeout.
                try:
                    await page.wait_for_load_state("networkidle", timeout=15_000)
                except Exception:
                    pass  # timeout is acceptable; page may still be settling

                # Extra settle time for any async challenge JS
                await page.wait_for_timeout(3000)

                # Retry-safe content extraction.
                # If the page is still navigating (e.g. a late redirect from
                # a challenge), wait and retry up to 3 times.
                html = await _safe_content(page, retries=3, wait_ms=2000)
                if html is None:
                    # Fallback: try once more after a longer settle
                    await page.wait_for_timeout(5000)
                    html = await _safe_content(page, retries=0, wait_ms=0)
                    if html is None:
                        html = ""

                cookies_list = await context.cookies()
                cookies = {c["name"]: c["value"] for c in cookies_list}
                response_status = response.status if response else 200

                duration = time.time() - start
                logger.debug(
                    f"playwright completed: status={response_status}, "
                    f"cookies={list(cookies.keys())}, duration={duration:.1f}s"
                )

                return BypassResult(
                    success=True,
                    html=html,
                    cookies=cookies,
                    strategy_name=self.name,
                    level=self.level,
                    duration=duration,
                    status_code=response_status,
                )

        except Exception as e:
            duration = time.time() - start
            logger.debug(f"playwright failed: {e}")
            return BypassResult(
                success=False,
                error=str(e),
                strategy_name=self.name,
                level=self.level,
                duration=duration,
            )

        finally:
            if browser and not keep_open:
                try:
                    await browser.close()
                except Exception:
                    pass
            elif browser and keep_open:
                logger.info(
                    "Browser kept open (--keep-open). "
                    "Close the browser window manually when done."
                )

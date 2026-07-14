"""Level 4: nodriver — CDP-level stealth browser.

nodriver connects directly to Chrome via the DevTools Protocol (CDP)
without going through Selenium/WebDriver bindings. This avoids the
automation protocol signatures that Cloudflare can detect in Playwright
and Selenium (Runtime.enable, Target.setAutoAttach, etc.).

This is the "ultimate weapon" for Cloudflare Managed Challenge when
L1-L3 have all failed.
"""

import time
from typing import Optional, Dict

import nodriver as uc

from cf_bypass.strategies.base import BaseStrategy, BypassResult
from cf_bypass.logging_config import get_logger

logger = get_logger("strategies.nodriver")

# Cloudflare challenge indicators (case-insensitive match against page text)
CF_CHALLENGE_INDICATORS: list[str] = [
    "just a moment",
    "checking your browser",
    "cf-browser-verification",
    "challenge-platform",
    "are you human",
    "verify you are human",
    "press and hold",
    "turnstile",
]


def _detect_challenge(html: str) -> Optional[str]:
    """Return the first challenge indicator found in *html*, or None."""
    if not html:
        return None
    html_lower = html.lower()
    for indicator in CF_CHALLENGE_INDICATORS:
        if indicator in html_lower:
            return indicator
    return None


class Level4Nodriver(BaseStrategy):
    """Level 4: nodriver — pure CDP-based browser automation.

    Zero WebDriver signatures. Chrome connects directly via CDP WebSocket.
    """

    @property
    def name(self) -> str:
        return "nodriver"

    @property
    def level(self) -> int:
        return 4

    async def bypass(
        self,
        url: str,
        proxy: Optional[str] = None,
        timeout: int = 60,
        headless: bool = False,
        existing_cookies: Optional[Dict[str, str]] = None,
        keep_open: bool = False,
    ) -> BypassResult:
        """Start Chrome via nodriver, navigate, and extract cookies."""
        start = time.time()
        browser = None

        try:
            browser_args: list = [
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
            ]

            if proxy:
                browser_args.append(f"--proxy-server={proxy}")

            browser = await uc.start(
                headless=headless,
                browser_args=browser_args,
            )

            page = await browser.get(url)

            # Wait for initial page load + challenge resolution.
            # CF Turnstile / Managed Challenge can take 5-15 seconds.
            settle_seconds = max(8, min(timeout // 2, 20))
            logger.debug(f"Waiting {settle_seconds}s for challenge resolution...")
            await page.sleep(settle_seconds)

            # First content capture — may still be challenge page
            html = await page.get_content() or ""

            # Detect if we landed on a challenge page
            challenge = _detect_challenge(html)
            if challenge:
                logger.info(f"Challenge detected: '{challenge}' — waiting longer...")
                # Wait additional time for auto-resolution (CF Turnstile
                # sometimes auto-passes if the fingerprint is clean)
                await page.sleep(10)
                html = await page.get_content() or ""
                challenge = _detect_challenge(html)
                if challenge:
                    logger.warning(
                        f"Challenge still present after extended wait: '{challenge}'. "
                        f"Manual intervention may be required."
                    )

            # Log current URL for debugging (may have been redirected)
            try:
                current_url = await page.evaluate("window.location.href")
                logger.debug(f"Current page URL: {current_url}")
            except Exception:
                pass

            # Extract cookies
            raw_cookies = await browser.cookies.get_all()
            cookies: Dict[str, str] = {}
            for c in raw_cookies:
                name = c.name if hasattr(c, "name") else c.get("name", "")
                value = c.value if hasattr(c, "value") else c.get("value", "")
                if name:
                    cookies[name] = value

            # Validate we got meaningful content
            html_len = len(html) if html else 0
            logger.debug(
                f"nodriver: html_len={html_len}, cookies={list(cookies.keys())}, "
                f"challenge_detected={challenge is not None}"
            )

            if html_len < 200 and challenge:
                # Still on challenge page with very little content
                return BypassResult(
                    success=True,
                    html=html,
                    cookies=cookies,
                    strategy_name=self.name,
                    level=self.level,
                    duration=time.time() - start,
                    status_code=200,
                    error=(
                        f"Challenge page still active ({challenge}). "
                        f"Try headed mode (--headless=false) for manual solving."
                    ),
                )

            duration = time.time() - start
            return BypassResult(
                success=True,
                html=html,
                cookies=cookies,
                strategy_name=self.name,
                level=self.level,
                duration=duration,
                status_code=200,
            )

        except Exception as e:
            duration = time.time() - start
            logger.debug(f"nodriver failed: {e}")
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
                    browser.stop()
                except Exception:
                    pass
            elif browser and keep_open:
                logger.info(
                    "Browser kept open (--keep-open). "
                    "Close the browser window manually when done."
                )

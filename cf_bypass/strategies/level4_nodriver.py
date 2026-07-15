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


async def _wait_for_challenge_resolution(page, timeout: int = 60) -> bool:
    """Poll until challenge disappears or timeout expires.

    Uses exponential backoff: starts at 2s, multiplies by 1.5× each
    iteration, capped at 10s.  Returns ``True`` when no challenge
    indicators remain in the page HTML, or ``False`` on timeout.
    """
    deadline = time.time() + timeout
    interval = 2.0  # initial polling interval in seconds
    while time.time() < deadline:
        try:
            html = await page.get_content()
        except Exception:
            await page.sleep(interval)
            interval = min(interval * 1.5, 10.0)
            continue
        challenge = _detect_challenge(html)
        if not challenge:
            return True
        logger.debug(
            f"Challenge '{challenge}' still active, "
            f"waiting {interval:.1f}s..."
        )
        await page.sleep(interval)
        interval = min(interval * 1.5, 10.0)  # exponential backoff, cap 10s
    return False


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
            from cf_bypass.strategies.stealth import get_l4_browser_args, apply_enhanced_stealth_l4

            browser_args: list = get_l4_browser_args()

            if proxy:
                browser_args.append(f"--proxy-server={proxy}")

            browser = await uc.start(
                headless=headless,
                browser_args=browser_args,
            )

            page = await browser.get(url)

            # Apply L4-specific CDP-level stealth patches
            await apply_enhanced_stealth_l4(page)

            # Wait for initial page load + challenge resolution.
            # CF Turnstile / Managed Challenge can take 5-15 seconds.
            settle_seconds = max(8, min(timeout // 2, 20))
            logger.debug(f"Waiting {settle_seconds}s for challenge resolution...")
            await page.sleep(settle_seconds)

            # First content capture — may still be challenge page
            html = await page.get_content() or ""

            # Detect if we landed on a challenge page
            challenge = _detect_challenge(html)
            retries = 0
            max_retries = 2

            while challenge and retries <= max_retries:
                if retries == 0:
                    logger.info(
                        f"Challenge detected: '{challenge}' — "
                        f"polling for resolution..."
                    )
                else:
                    logger.info(
                        f"Challenge still present after retry {retries}: "
                        f"'{challenge}' — reloading page..."
                    )
                    try:
                        await page.reload()
                    except Exception:
                        logger.debug("Page reload failed, continuing with current page")
                    await page.sleep(3)

                # Poll with exponential backoff until challenge clears or timeout
                remaining = timeout - int(time.time() - start)
                if remaining <= 0:
                    remaining = 30  # floor: give at least 30s for polling

                resolved = await _wait_for_challenge_resolution(
                    page, timeout=min(remaining, 60)
                )

                if resolved:
                    html = await page.get_content() or ""
                    challenge = _detect_challenge(html)
                    if not challenge:
                        logger.info("Challenge resolved automatically")
                        break

                retries += 1

            # Attempt Turnstile solver when challenge persists after polling
            if challenge and (
                "turnstile" in (challenge or "") or
                "challenge-platform" in (challenge or "")
            ):
                from cf_bypass.solvers.turnstile import TurnstileSolver

                sitekey = TurnstileSolver.extract_sitekey(html)
                if sitekey:
                    logger.info(
                        f"Attempting Turnstile solve for "
                        f"sitekey={sitekey[:20]}..."
                    )
                    solver = TurnstileSolver()
                    solve_result = await solver.solve(
                        page, sitekey, url,
                        timeout=min(timeout - int(time.time() - start), 60),
                    )
                    if solve_result.success:
                        logger.info(
                            f"Turnstile solved in {solve_result.duration:.1f}s"
                        )
                        # Wait briefly for page to process the token
                        await page.sleep(3)
                        html = await page.get_content() or ""
                        challenge = _detect_challenge(html)
                        if not challenge:
                            logger.info("Challenge cleared after Turnstile solve")
                    else:
                        logger.warning(
                            f"Turnstile solve failed: {solve_result.error}"
                        )
                else:
                    logger.debug(
                        "Turnstile/challenge-platform detected but no "
                        "sitekey found in HTML"
                    )

            # Manual intervention mode — when headed and challenge persists
            if challenge and not headless:
                manual_timeout = min(
                    timeout - int(time.time() - start), 120
                )
                logger.info(
                    f"\n{'=' * 60}\n"
                    f"  ⚠️  CHALLENGE DETECTED: '{challenge}'\n"
                    f"  Browser window is OPEN — please complete the\n"
                    f"  verification manually (click checkbox, solve puzzle, etc.).\n"
                    f"  Waiting up to {manual_timeout}s for manual resolution...\n"
                    f"{'=' * 60}"
                )
                resolved = await _wait_for_challenge_resolution(
                    page, timeout=manual_timeout
                )
                if resolved:
                    logger.info("✅ Challenge resolved manually!")
                    html = await page.get_content() or ""
                    challenge = None
                else:
                    logger.warning(
                        f"Manual intervention timed out after {manual_timeout}s"
                    )
                    return BypassResult(
                        success=True,
                        html=html,
                        cookies=cookies,
                        strategy_name=self.name,
                        level=self.level,
                        duration=time.time() - start,
                        status_code=200,
                        challenge_detected=True,
                        challenge_type=challenge,
                        manual_intervention_needed=True,
                        error=(
                            f"Manual intervention timeout ({manual_timeout}s). "
                            f"Challenge '{challenge}' still active."
                        ),
                    )

            if challenge:
                logger.warning(
                    f"Challenge still present after {retries} retry(ies): "
                    f"'{challenge}'. Manual intervention may be required."
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

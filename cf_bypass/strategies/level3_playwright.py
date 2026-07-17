"""Level 3: playwright + playwright-stealth — full browser automation.

Launches a real Chromium browser, applies stealth patches to hide
automation signatures (navigator.webdriver, CDP Runtime.events, etc.),
navigates to the target page, waits for challenges to resolve, and
extracts the resulting cookies.

v2.0: Integrates L5 humanize behavior and L6 fingerprint layers.

This is the primary strategy for Cloudflare Managed Challenge.
"""

import time
import random
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

                # Apply enhanced anti-detection patches (stealth + extra evasion)
                from cf_bypass.strategies.stealth import apply_enhanced_stealth_l3, apply_headless_evasions_l3
                await apply_enhanced_stealth_l3(page)

                # Headless-specific CDP evasions (UA cleanup, etc.)
                if headless:
                    try:
                        await apply_headless_evasions_l3(page)
                    except Exception as exc:
                        logger.debug(f"Headless CDP evasions skipped: {exc}")

                # ---- v2.0: Apply fingerprint layer (L6) ----
                try:
                    from cf_bypass.fingerprint.canvas import CanvasNoiseInjector
                    from cf_bypass.fingerprint.audio import AudioNoiseInjector
                    from cf_bypass.fingerprint.fonts import FontSpoofer

                    import random as _random
                    canvas_seed = _random.randint(0, 65535)
                    audio_seed = _random.randint(0, 65535)

                    canvas_injector = CanvasNoiseInjector(seed=canvas_seed, mode="subtle")
                    audio_injector = AudioNoiseInjector(seed=audio_seed)
                    font_spoofer = FontSpoofer()

                    await page.add_init_script(canvas_injector.get_script())
                    await page.add_init_script(audio_injector.get_script())
                    await page.add_init_script(font_spoofer.get_script())
                    logger.debug("L6 fingerprint layer applied (canvas, audio, fonts)")
                except Exception as exc:
                    logger.debug(f"L6 fingerprint layer skipped: {exc}")

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

                # ---- v2.0: Apply humanize warm-up (L5) ----
                try:
                    from cf_bypass.humanize.behavior_synth import BehaviorSynth
                    synth = BehaviorSynth(page)
                    domain = urlparse(url).netloc
                    # Light pre-navigation behavior
                    await synth.pre_navigate()
                    logger.debug("L5 pre-navigation behavior applied")
                except Exception as exc:
                    logger.debug(f"L5 behavior skipped: {exc}")

                # Navigate to target
                logger.debug(f"Navigating to {url}")
                response = await page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=timeout * 1000,
                )

                # ---- v2.0: Post-navigation behavior (L5) ----
                try:
                    await synth.post_navigate()
                    # Light page interaction to appear human
                    await synth.scroll.scroll_down(random.uniform(0, 300))
                except Exception:
                    pass

                # Wait for post-load challenge resolution.
                try:
                    await page.wait_for_load_state("networkidle", timeout=15_000)
                except Exception:
                    pass

                # Extra settle time for any async challenge JS
                await page.wait_for_timeout(3000)

                # Retry-safe content extraction.
                html = await _safe_content(page, retries=3, wait_ms=2000)
                if html is None:
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

                # v2.0: Detect challenge status
                challenge_detected = False
                challenge_type = None
                if html:
                    html_lower = html.lower()
                    if "turnstile" in html_lower:
                        challenge_detected = True
                        challenge_type = "turnstile"
                    elif any(kw in html_lower for kw in ["just a moment", "checking your browser"]):
                        challenge_detected = True
                        challenge_type = "managed_challenge"

                return BypassResult(
                    success=True,
                    html=html,
                    cookies=cookies,
                    strategy_name=self.name,
                    level=self.level,
                    duration=duration,
                    status_code=response_status,
                    challenge_detected=challenge_detected,
                    challenge_type=challenge_type,
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

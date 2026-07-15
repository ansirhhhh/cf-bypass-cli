"""Persistent browser session with hot-swappable URL page.

Keeps a headed (or headless) Chromium browser alive for the entire session,
exposing a single "active page" that can be *closed and replaced* on demand.

This is the runtime used by the :mod:`cf_bypass.cli` ``monitor`` subcommand,
which implements the ``/change`` slash command:

    1. User types ``/change`` in the CLI
    2. CLI prompts for the new URL
    3. ``PersistentBrowserSession.change_target(new_url)`` is called:
         - old page is explicitly **closed**
         - new page is created, stealth is applied
         - browser navigates to the new URL

The browser context (and thus cookies, localStorage, anti-fingerprinting
parameters) is preserved across ``/change`` calls so that accumulated
Cloudflare clearances remain available for other pages on the same domain.
"""

from __future__ import annotations

import time
from typing import Optional, Dict

from urllib.parse import urlparse

from playwright.async_api import (
    async_playwright,
    Playwright,
    Browser,
    BrowserContext,
    Page,
)
from playwright_stealth import Stealth

from cf_bypass.logging_config import get_logger
from cf_bypass.utils import normalize_url

logger = get_logger("browser_session")

# Mirrors level3_playwright.CHROME_USER_AGENT so anti-detection behaviour is
# identical between a one-shot bypass and a persistent session.
CHROME_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


class PersistentBrowserSession:
    """Long-lived Playwright browser with a single replaceable page.

    Typical usage (async context manager)::

        async with PersistentBrowserSession(proxy=..., headless=False) as sess:
            await sess.navigate_to("https://target-a.com")
            ...
            # User requests /change
            await sess.change_target("https://target-b.com")   # closes old page
            ...

    The browser itself (and its context) survive ``change_target`` — only
    the individual page is destroyed and recreated.
    """

    def __init__(
        self,
        proxy: Optional[str] = None,
        headless: bool = False,
        viewport: Optional[Dict[str, int]] = None,
    ) -> None:
        self._proxy = proxy
        self._headless = headless
        self._viewport = viewport or {"width": 1920, "height": 1080}

        # Playwright resource handles — populated by start()
        self._pw: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None

        self._current_url: Optional[str] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Launch the browser + context (idempotent)."""
        if self._browser is not None:
            return

        logger.info("Launching persistent browser session "
                    f"(headless={self._headless})")

        self._pw = await async_playwright().start()

        launch_kwargs: dict = {
            "headless": self._headless,
            "args": [
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
            ],
        }
        if self._proxy:
            launch_kwargs["proxy"] = {"server": self._proxy}

        self._browser = await self._pw.chromium.launch(**launch_kwargs)

        context_kwargs: dict = {
            "viewport": self._viewport,
            "user_agent": CHROME_USER_AGENT,
            "locale": "en-US",
            "timezone_id": "America/New_York",
        }
        self._context = await self._browser.new_context(**context_kwargs)
        logger.debug("Persistent browser session ready")

    async def stop(self) -> None:
        """Tear down browser, context, pages."""
        if self._page is not None:
            try:
                await self._page.close()
            except Exception:
                pass
            self._page = None
        if self._context is not None:
            try:
                await self._context.close()
            except Exception:
                pass
            self._context = None
        if self._browser is not None:
            try:
                await self._browser.close()
            except Exception:
                pass
            self._browser = None
        if self._pw is not None:
            try:
                await self._pw.stop()
            except Exception:
                pass
            self._pw = None
        logger.info("Persistent browser session stopped")

    # ------------------------------------------------------------------
    # Async context manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> "PersistentBrowserSession":
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.stop()

    # ------------------------------------------------------------------
    # Core: navigate / hot-swap
    # ------------------------------------------------------------------

    async def navigate_to(
        self,
        url: str,
        *,
        timeout: int = 90,
    ) -> bool:
        """Open *url* in the currently active page (without closing it).

        Creates the page on first call.  Use :meth:`change_target` when you
        explicitly want the old page closed.
        """
        assert self._browser is not None, (
            "Session not started — call start() or use async context manager"
        )
        assert self._context is not None

        url = normalize_url(url)

        if self._page is None:
            self._page = await self._create_new_page()

        logger.info(f"Navigating existing page to {url}")
        self._current_url = url
        try:
            await self._page.goto(
                url,
                wait_until="networkidle",
                timeout=timeout * 1000,
            )
            # Allow extra time for on-load challenges
            await self._page.wait_for_timeout(2000)
            try:
                await self._page.wait_for_load_state("networkidle", timeout=10_000)
            except Exception:
                pass
            return True
        except Exception as exc:
            logger.warning(f"Navigation to {url} failed: {exc}")
            return False

    async def change_target(
        self,
        new_url: str,
        *,
        timeout: int = 90,
    ) -> bool:
        """Close the current page (if any), open a *brand new* one on *new_url*.

        This is the behaviour backing the ``/change`` CLI command.  Closing
        the old page guarantees no stale event handlers, memory, or DOM
        references leak between targets.
        """
        assert self._browser is not None
        assert self._context is not None

        new_url = normalize_url(new_url)

        # ------------------------------------------------------------
        # 1. Explicitly close the current page ("关闭当前这个网页")
        # ------------------------------------------------------------
        if self._page is not None:
            logger.info("Closing current page before opening new target")
            try:
                await self._page.close()
            except Exception as exc:
                logger.debug(f"Ignoring error while closing old page: {exc}")
            self._page = None

        # ------------------------------------------------------------
        # 2. Create a fresh page, apply stealth, navigate
        # ------------------------------------------------------------
        logger.info(f"Opening NEW page for target: {new_url}")
        self._page = await self._create_new_page()
        self._current_url = new_url
        try:
            await self._page.goto(
                new_url,
                wait_until="networkidle",
                timeout=timeout * 1000,
            )
            await self._page.wait_for_timeout(2000)
            try:
                await self._page.wait_for_load_state("networkidle", timeout=10_000)
            except Exception:
                pass
            return True
        except Exception as exc:
            logger.warning(f"Navigation to {new_url} failed after page swap: {exc}")
            return False

    async def reload(self, timeout: int = 60) -> bool:
        """Reload the current page (keeps the page object alive)."""
        if self._page is None:
            logger.warning("reload() called with no active page")
            return False
        try:
            await self._page.reload(
                wait_until="networkidle",
                timeout=timeout * 1000,
            )
            return True
        except Exception as exc:
            logger.warning(f"Reload failed: {exc}")
            return False

    # ------------------------------------------------------------------
    # State inspection
    # ------------------------------------------------------------------

    @property
    def current_url(self) -> Optional[str]:
        return self._current_url

    @property
    def has_page(self) -> bool:
        return self._page is not None

    async def get_page_url(self) -> Optional[str]:
        """Return the page's *actual* location (after redirects)."""
        if self._page is None:
            return None
        return self._page.url

    async def get_html(self) -> Optional[str]:
        if self._page is None:
            return None
        try:
            return await self._page.content()
        except Exception as exc:
            logger.debug(f"get_html failed: {exc}")
            return None

    async def get_cookies(self, url: Optional[str] = None) -> Dict[str, str]:
        """Return cookies from the browser context."""
        if self._context is None:
            return {}
        target_url = url or self._current_url
        try:
            if target_url:
                raw = await self._context.cookies(target_url)
            else:
                raw = await self._context.cookies()
            return {c["name"]: c["value"] for c in raw}
        except Exception as exc:
            logger.debug(f"get_cookies failed: {exc}")
            return {}

    async def add_cookies(
        self,
        cookies: Dict[str, str],
        for_url: str,
    ) -> None:
        """Inject cookies for *for_url*'s domain into the context."""
        if not cookies or self._context is None:
            return
        domain = urlparse(for_url).netloc
        objs = [
            {
                "name": k,
                "value": v,
                "domain": domain,
                "path": "/",
            }
            for k, v in cookies.items()
        ]
        try:
            await self._context.add_cookies(objs)
        except Exception as exc:
            logger.debug(f"add_cookies failed: {exc}")

    async def wait_for_seconds(self, seconds: float) -> None:
        """Utility sleep — useful for user-triggered waits."""
        if self._page is not None:
            await self._page.wait_for_timeout(int(seconds * 1000))
        else:
            import asyncio
            await asyncio.sleep(seconds)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _create_new_page(self) -> Page:
        """Create a new page in the current context and apply stealth patches.

        Always goes through this helper so every page we hand to the user
        has the same anti-detection treatment applied (consistent with
        level3_playwright bypass behaviour).
        """
        assert self._context is not None
        page = await self._context.new_page()
        from cf_bypass.strategies.stealth import apply_enhanced_stealth_l3
        await apply_enhanced_stealth_l3(page)
        logger.debug("New page created with enhanced stealth applied")
        return page

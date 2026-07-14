"""Level 1: cloudscraper — lightweight JS challenge solver.

cloudscraper is a synchronous library that reverse-engineers Cloudflare's
JS challenge and executes it inside a Python JS runtime. Fast and lightweight
but only works against lower-level CF protections (not Managed Challenge).
"""

import asyncio
import time
from typing import Optional, Dict

import cloudscraper

from cf_bypass.strategies.base import BaseStrategy, BypassResult
from cf_bypass.logging_config import get_logger

logger = get_logger("strategies.cloudscraper")


class Level1Cloudscraper(BaseStrategy):
    """Level 1: cloudscraper — lightweight JS challenge bypass.

    Uses a thread-pool executor to avoid blocking the event loop since
    cloudscraper is synchronous.
    """

    @property
    def name(self) -> str:
        return "cloudscraper"

    @property
    def level(self) -> int:
        return 1

    async def bypass(
        self,
        url: str,
        proxy: Optional[str] = None,
        timeout: int = 60,
        headless: bool = False,
        existing_cookies: Optional[Dict[str, str]] = None,
        keep_open: bool = False,
    ) -> BypassResult:
        """Run cloudscraper in a thread pool to keep the event loop free."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            self._sync_bypass,
            url,
            proxy,
            timeout,
            existing_cookies,
        )

    def _sync_bypass(
        self,
        url: str,
        proxy: Optional[str] = None,
        timeout: int = 60,
        existing_cookies: Optional[Dict[str, str]] = None,
    ) -> BypassResult:
        """Synchronous cloudscraper call wrapped by bypass()."""
        start = time.time()
        try:
            # cloudscraper.create_scraper() forwards kwargs to requests.Session,
            # which does NOT accept 'timeout'.  Pass timeout to get() only.
            scraper_kwargs: dict = {
                "browser": {
                    "browser": "chrome",
                    "platform": "windows",
                    "mobile": False,
                }
            }
            if proxy:
                scraper_kwargs["proxies"] = {"http": proxy, "https": proxy}

            scraper = cloudscraper.create_scraper(**scraper_kwargs)

            if existing_cookies:
                for name, value in existing_cookies.items():
                    scraper.cookies.set(name, value)

            response = scraper.get(url, timeout=timeout)

            duration = time.time() - start
            cookies = dict(response.cookies)

            logger.debug(
                f"cloudscraper completed: status={response.status_code}, "
                f"cookies={list(cookies.keys())}, duration={duration:.1f}s"
            )

            return BypassResult(
                success=True,
                html=response.text,
                cookies=cookies,
                strategy_name=self.name,
                level=self.level,
                duration=duration,
                status_code=response.status_code,
            )

        except Exception as e:
            duration = time.time() - start
            logger.debug(f"cloudscraper failed: {e}")
            return BypassResult(
                success=False,
                error=str(e),
                strategy_name=self.name,
                level=self.level,
                duration=duration,
            )

"""Level 2: curl_cffi — TLS fingerprint impersonation.

curl_cffi mimics browser TLS handshake signatures (JA3/JA4 fingerprints)
at the C level, making requests appear to come from a real Chrome/Firefox
binary. Natively async via its AsyncSession.
"""

import time
from typing import Optional, Dict

from curl_cffi.requests import AsyncSession

from cf_bypass.strategies.base import BaseStrategy, BypassResult
from cf_bypass.logging_config import get_logger

logger = get_logger("strategies.curl_cffi")

# Chrome 120 on Windows — a widely trusted fingerprint
DEFAULT_IMPERSONATE = "chrome120"


class Level2CurlCffi(BaseStrategy):
    """Level 2: curl_cffi — TLS fingerprint impersonation.

    Natively async, so no thread-pool wrapping needed.
    """

    @property
    def name(self) -> str:
        return "curl_cffi"

    @property
    def level(self) -> int:
        return 2

    async def bypass(
        self,
        url: str,
        proxy: Optional[str] = None,
        timeout: int = 60,
        headless: bool = False,
        existing_cookies: Optional[Dict[str, str]] = None,
        keep_open: bool = False,
    ) -> BypassResult:
        """Make a curl_cffi GET request with browser-like TLS fingerprint."""
        start = time.time()
        try:
            session_kwargs: dict = {
                "timeout": timeout,
                "impersonate": DEFAULT_IMPERSONATE,
                "allow_redirects": True,
            }
            if proxy:
                session_kwargs["proxies"] = {"http": proxy, "https": proxy}

            async with AsyncSession(**session_kwargs) as session:
                if existing_cookies:
                    session.cookies.update(existing_cookies)

                response = await session.get(url)

                duration = time.time() - start
                cookies = dict(response.cookies)

                logger.debug(
                    f"curl_cffi completed: status={response.status_code}, "
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
            logger.debug(f"curl_cffi failed: {e}")
            return BypassResult(
                success=False,
                error=str(e),
                strategy_name=self.name,
                level=self.level,
                duration=duration,
            )

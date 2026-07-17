"""2Captcha API provider.

Supports Turnstile, reCAPTCHA v2/v3, hCaptcha, and image captcha
via the 2Captcha API (in.php / res.php polling pattern).

API docs: https://2captcha.com/2captcha-api
"""

import time
from typing import Optional

import httpx

from cf_bypass.solvers.providers.base import BaseProvider, ProviderResult
from cf_bypass.solvers.providers import register_provider
from cf_bypass.logging_config import get_logger

logger = get_logger("solvers.twocaptcha")

TWOCAPTCHA_IN = "https://api.2captcha.com/in.php"
TWOCAPTCHA_RES = "https://api.2captcha.com/res.php"
POLL_INTERVAL = 2.0


@register_provider("2captcha")
class TwoCaptchaProvider(BaseProvider):
    """CAPTCHA solving via 2Captcha API.

    Supports: Turnstile, reCAPTCHA v2, reCAPTCHA v3, hCaptcha, image.

    Usage::

        provider = TwoCaptchaProvider(api_key="YOUR_KEY")
        result = await provider.solve_recaptcha_v2(sitekey, url)
    """

    def __init__(self, api_key: str = ""):
        self.api_key = api_key

    @property
    def name(self) -> str:
        return "2captcha"

    # ------------------------------------------------------------------
    # Turnstile
    # ------------------------------------------------------------------

    async def solve_turnstile(
        self,
        sitekey: str,
        page_url: str,
        timeout: int = 120,
    ) -> ProviderResult:
        return await self._submit_and_poll(
            method="turnstile",
            params={
                "sitekey": sitekey,
                "pageurl": page_url,
            },
            timeout=timeout,
        )

    # ------------------------------------------------------------------
    # reCAPTCHA v2
    # ------------------------------------------------------------------

    async def solve_recaptcha_v2(
        self,
        sitekey: str,
        page_url: str,
        is_invisible: bool = False,
        timeout: int = 120,
    ) -> ProviderResult:
        params = {
            "googlekey": sitekey,
            "pageurl": page_url,
        }
        if is_invisible:
            params["invisible"] = "1"

        return await self._submit_and_poll(
            method="userrecaptcha",
            params=params,
            timeout=timeout,
        )

    # ------------------------------------------------------------------
    # reCAPTCHA v3
    # ------------------------------------------------------------------

    async def solve_recaptcha_v3(
        self,
        sitekey: str,
        page_url: str,
        action: str = "verify",
        min_score: float = 0.9,
        timeout: int = 120,
    ) -> ProviderResult:
        return await self._submit_and_poll(
            method="userrecaptcha",
            params={
                "googlekey": sitekey,
                "pageurl": page_url,
                "version": "v3",
                "action": action,
                "min_score": min_score,
            },
            timeout=timeout,
        )

    # ------------------------------------------------------------------
    # hCaptcha
    # ------------------------------------------------------------------

    async def solve_hcaptcha(
        self,
        sitekey: str,
        page_url: str,
        timeout: int = 120,
    ) -> ProviderResult:
        return await self._submit_and_poll(
            method="hcaptcha",
            params={
                "sitekey": sitekey,
                "pageurl": page_url,
            },
            timeout=timeout,
        )

    # ------------------------------------------------------------------
    # Image captcha
    # ------------------------------------------------------------------

    async def solve_image(
        self,
        image_base64: str,
        instruction: str = "",
        timeout: int = 60,
    ) -> ProviderResult:
        params = {
            "body": image_base64,
        }
        if instruction:
            params["textinstructions"] = instruction

        return await self._submit_and_poll(
            method="base64",
            params=params,
            timeout=timeout,
        )

    # ------------------------------------------------------------------
    # Core logic
    # ------------------------------------------------------------------

    async def _submit_and_poll(
        self,
        method: str,
        params: dict,
        timeout: int = 120,
    ) -> ProviderResult:
        """Submit a captcha to 2Captcha and poll for the answer."""
        if not self.api_key:
            return ProviderResult(
                success=False,
                error="No 2Captcha API key configured",
                provider_name=self.name,
            )

        start = time.time()

        try:
            captcha_id = await self._submit(method, params)
            if not captcha_id:
                return ProviderResult(
                    success=False,
                    duration=time.time() - start,
                    error="Failed to submit captcha to 2Captcha",
                    provider_name=self.name,
                )

            logger.debug(f"2Captcha task submitted: id={captcha_id} method={method}")

            token = await self._poll(captcha_id, timeout=timeout)
            duration = time.time() - start

            if token and token != "ERROR_CAPTCHA_UNSOLVABLE":
                return ProviderResult(
                    token=token,
                    success=True,
                    duration=round(duration, 2),
                    provider_name=self.name,
                )

            return ProviderResult(
                success=False,
                duration=round(duration, 2),
                error=f"2Captcha failed: {token or 'timeout'}",
                provider_name=self.name,
            )

        except Exception as exc:
            logger.debug(f"2Captcha error: {exc}")
            return ProviderResult(
                success=False,
                duration=time.time() - start,
                error=str(exc),
                provider_name=self.name,
            )

    async def _submit(self, method: str, params: dict) -> Optional[str]:
        """Submit captcha and return captcha_id."""
        form = {
            "key": self.api_key,
            "method": method,
            "json": "1",
            **params,
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(TWOCAPTCHA_IN, data=form)
                data = resp.json()

                if data.get("status") != 1:
                    error = data.get("error_text", data.get("request", "Unknown"))
                    logger.warning(f"2Captcha submit error: {error}")
                    return None

                return data.get("request")  # captcha_id

        except Exception as exc:
            logger.warning(f"2Captcha submit request failed: {exc}")
            return None

    async def _poll(
        self,
        captcha_id: str,
        timeout: int = 120,
    ) -> Optional[str]:
        """Poll 2Captcha until solution is ready. Returns token or None."""
        deadline = time.time() + timeout

        while time.time() < deadline:
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.get(TWOCAPTCHA_RES, params={
                        "key": self.api_key,
                        "action": "get",
                        "id": captcha_id,
                        "json": "1",
                    })
                    data = resp.json()

                    if data.get("status") == 1:
                        return data.get("request")  # the solution token

                    error = data.get("request", "")
                    if error == "ERROR_CAPTCHA_UNSOLVABLE":
                        logger.warning("2Captcha: captcha unsolvable")
                        return "ERROR_CAPTCHA_UNSOLVABLE"

                    if error and error != "CAPCHA_NOT_READY":
                        logger.debug(f"2Captcha poll status: {error}")

                    await self._sleep(POLL_INTERVAL)

            except Exception as exc:
                logger.debug(f"2Captcha poll error (retrying): {exc}")
                await self._sleep(POLL_INTERVAL)

        return None

    @staticmethod
    async def _sleep(seconds: float) -> None:
        import asyncio
        await asyncio.sleep(seconds)

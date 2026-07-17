"""Capsolver API provider.

Supports Turnstile, reCAPTCHA v2/v3, and hCaptcha via the Capsolver
createTask / getTaskResult polling pattern.

API docs: https://docs.capsolver.com/
"""

import time
from typing import Optional

import httpx

from cf_bypass.solvers.providers.base import BaseProvider, ProviderResult
from cf_bypass.solvers.providers import register_provider
from cf_bypass.logging_config import get_logger

logger = get_logger("solvers.capsolver")

CAPSOLVER_BASE = "https://api.capsolver.com"
CREATE_TASK = f"{CAPSOLVER_BASE}/createTask"
GET_RESULT = f"{CAPSOLVER_BASE}/getTaskResult"
BALANCE = f"{CAPSOLVER_BASE}/getBalance"
POLL_INTERVAL = 2.0  # seconds


@register_provider("capsolver")
class CapsolverProvider(BaseProvider):
    """CAPTCHA solving via Capsolver API.

    Supports: Turnstile, reCAPTCHA v2, reCAPTCHA v3, hCaptcha, image.

    Usage::

        provider = CapsolverProvider(api_key="CAP-...")
        result = await provider.solve_turnstile(sitekey, url, timeout=120)
    """

    # Task type mapping
    TASK_TYPES = {
        "turnstile": "AntiTurnstileTaskProxyLess",
        "recaptcha_v2": "ReCaptchaV2TaskProxyLess",
        "recaptcha_v2_enterprise": "ReCaptchaV2EnterpriseTaskProxyLess",
        "recaptcha_v3": "ReCaptchaV3TaskProxyLess",
        "recaptcha_v3_enterprise": "ReCaptchaV3EnterpriseTaskProxyLess",
        "hcaptcha": "HCaptchaTaskProxyLess",
        "image": "ImageToTextTask",
    }

    def __init__(self, api_key: str = ""):
        self.api_key = api_key

    @property
    def name(self) -> str:
        return "capsolver"

    # ------------------------------------------------------------------
    # Turnstile
    # ------------------------------------------------------------------

    async def solve_turnstile(
        self,
        sitekey: str,
        page_url: str,
        timeout: int = 120,
    ) -> ProviderResult:
        return await self._solve(
            task_type="turnstile",
            task_payload={
                "websiteURL": page_url,
                "websiteKey": sitekey,
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
        task_type = "recaptcha_v2"
        payload: dict = {
            "websiteURL": page_url,
            "websiteKey": sitekey,
        }
        if is_invisible:
            payload["isInvisible"] = True

        return await self._solve(
            task_type=task_type,
            task_payload=payload,
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
        return await self._solve(
            task_type="recaptcha_v3",
            task_payload={
                "websiteURL": page_url,
                "websiteKey": sitekey,
                "pageAction": action,
                "minScore": min_score,
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
        return await self._solve(
            task_type="hcaptcha",
            task_payload={
                "websiteURL": page_url,
                "websiteKey": sitekey,
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
        payload: dict = {
            "type": self.TASK_TYPES["image"],
            "body": image_base64,
        }
        if instruction:
            payload["module"] = instruction

        return await self._solve_raw(payload, timeout=timeout)

    # ------------------------------------------------------------------
    # Core solver logic
    # ------------------------------------------------------------------

    async def _solve(
        self,
        task_type: str,
        task_payload: dict,
        timeout: int = 120,
    ) -> ProviderResult:
        """Submit task and poll for result."""
        task_type_id = self.TASK_TYPES.get(task_type)
        if not task_type_id:
            return ProviderResult(
                success=False,
                error=f"Unknown task type: {task_type}",
                provider_name=self.name,
            )

        payload = {
            "type": task_type_id,
            **task_payload,
        }
        return await self._solve_raw(payload, timeout=timeout)

    async def _solve_raw(
        self,
        task_payload: dict,
        timeout: int = 120,
    ) -> ProviderResult:
        """Low-level createTask + poll loop."""
        if not self.api_key:
            return ProviderResult(
                success=False,
                error="No Capsolver API key configured",
                provider_name=self.name,
            )

        start = time.time()

        try:
            task_id = await self._create_task(task_payload)
            if not task_id:
                return ProviderResult(
                    success=False,
                    duration=time.time() - start,
                    error="Failed to create Capsolver task",
                    provider_name=self.name,
                )

            logger.debug(
                f"Capsolver task created: {task_id[:20]}... "
                f"type={task_payload.get('type', '?')}"
            )

            solution = await self._poll_task(task_id, timeout=timeout)
            duration = time.time() - start

            if solution:
                # Extract token from solution (field name varies by task type)
                token = (
                    solution.get("token")
                    or solution.get("gRecaptchaResponse")
                    or solution.get("hCaptchaResponse")
                    or solution.get("text")
                    or solution.get("cf_clearance")
                )
                if token:
                    return ProviderResult(
                        token=token,
                        success=True,
                        duration=round(duration, 2),
                        provider_name=self.name,
                        raw_response=solution,
                    )

            return ProviderResult(
                success=False,
                duration=round(duration, 2),
                error="Capsolver task timed out",
                provider_name=self.name,
            )

        except Exception as exc:
            logger.debug(f"Capsolver error: {exc}")
            return ProviderResult(
                success=False,
                duration=time.time() - start,
                error=str(exc),
                provider_name=self.name,
            )

    async def _create_task(self, task_payload: dict) -> Optional[str]:
        """Submit a task to Capsolver. Returns task_id or None."""
        payload = {
            "clientKey": self.api_key,
            "task": task_payload,
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(CREATE_TASK, json=payload)
                data = resp.json()

                if data.get("errorId") != 0:
                    error_desc = data.get("errorDescription", "Unknown error")
                    error_code = data.get("errorCode", "")
                    logger.warning(
                        f"Capsolver createTask error [{error_code}]: {error_desc}"
                    )
                    return None

                return data.get("taskId")

        except Exception as exc:
            logger.warning(f"Capsolver createTask request failed: {exc}")
            return None

    async def _poll_task(
        self,
        task_id: str,
        timeout: int = 120,
    ) -> Optional[dict]:
        """Poll Capsolver until task completes or timeout expires.

        Returns the ``solution`` dict on success, or None.
        """
        deadline = time.time() + timeout

        while time.time() < deadline:
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.post(GET_RESULT, json={
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
                        return data.get("solution", {})

                    # Still processing
                    await self._sleep(POLL_INTERVAL)

            except Exception as exc:
                logger.debug(f"Capsolver poll error (retrying): {exc}")
                await self._sleep(POLL_INTERVAL)

        return None

    @staticmethod
    async def _sleep(seconds: float) -> None:
        import asyncio
        await asyncio.sleep(seconds)

    # ------------------------------------------------------------------
    # Utility: check account balance
    # ------------------------------------------------------------------

    async def get_balance(self) -> Optional[float]:
        """Query Capsolver account balance. Returns USD or None on error."""
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(BALANCE, json={
                    "clientKey": self.api_key,
                })
                data = resp.json()
                if data.get("errorId") == 0:
                    return float(data.get("balance", 0))
        except Exception as exc:
            logger.debug(f"Capsolver balance check failed: {exc}")
        return None

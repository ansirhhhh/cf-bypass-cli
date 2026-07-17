"""Generic image-based CAPTCHA solver.

Handles traditional image-to-text CAPTCHAs that don't fit the
reCAPTCHA/Turnstile/hCaptcha categories. Falls back to LLM vision
when available, or delegates to 2Captcha/Capsolver image tasks.
"""

import base64
import time
from typing import Optional, Union

from cf_bypass.solvers.base import BaseSolver, SolverResult
from cf_bypass.logging_config import get_logger

logger = get_logger("solvers.image_captcha")


class ImageCaptchaSolver(BaseSolver):
    """Solve generic image-based CAPTCHAs.

    Supports:
    - Screenshot-based solving (capture element → send to provider)
    - Base64 image solving (pre-captured images)
    - LLM vision fallback (when configured)

    Usage::

        solver = ImageCaptchaSolver()
        # From a page element
        result = await solver.solve_from_element(page, ".captcha-image")
        # From base64
        result = await solver.solve_from_base64(img_b64, instruction="Type the text")
    """

    def __init__(self, dispatcher=None, llm_provider=None):
        """Initialize with optional dispatcher and LLM provider.

        Args:
            dispatcher: CaptchaDispatcher for routing to API providers.
            llm_provider: Optional LLM vision provider for free-form solving.
        """
        self.dispatcher = dispatcher
        self.llm_provider = llm_provider

    @property
    def name(self) -> str:
        return "image_captcha"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def solve(
        self,
        page_or_html,
        sitekey: str = "",
        url: str = "",
        timeout: int = 60,
    ) -> SolverResult:
        """Solve a generic image captcha.

        Since image captchas don't have sitekeys, the *sitekey* parameter
        is repurposed as an optional instruction string.
        """
        # For image captcha, sitekey isn't meaningful — use solve_from_element
        # or solve_from_base64 directly instead.
        if hasattr(page_or_html, "screenshot"):
            return await self.solve_from_element(
                page_or_html, "img[src*='captcha']",
                instruction=sitekey or "Type the characters in the image",
                timeout=timeout,
            )
        return SolverResult(
            success=False,
            error="Image captcha requires solve_from_element() or solve_from_base64()",
        )

    async def solve_from_element(
        self,
        page,
        selector: str,
        instruction: str = "Type the characters in the image",
        timeout: int = 60,
    ) -> SolverResult:
        """Screenshot a page element and solve it as an image captcha.

        Args:
            page: Browser page object (playwright or nodriver).
            selector: CSS selector for the captcha image element.
            instruction: Description for the solver (e.g. "click the traffic lights").
            timeout: Maximum wait time.

        Returns:
            SolverResult with token=the recognized text.
        """
        start = time.time()

        try:
            # Get the element screenshot as base64
            element = await page.query_selector(selector)
            if not element:
                return SolverResult(
                    success=False,
                    duration=time.time() - start,
                    error=f"Element not found: {selector}",
                )

            screenshot_bytes = await element.screenshot()
            img_b64 = base64.b64encode(screenshot_bytes).decode("utf-8")

            return await self.solve_from_base64(
                img_b64,
                instruction=instruction,
                timeout=timeout,
                start_time=start,
            )

        except Exception as exc:
            return SolverResult(
                success=False,
                duration=time.time() - start,
                error=str(exc),
            )

    async def solve_from_base64(
        self,
        image_base64: str,
        instruction: str = "Type the characters in the image",
        timeout: int = 60,
        start_time: Optional[float] = None,
    ) -> SolverResult:
        """Solve from a base64-encoded image string.

        Tries: 1) dispatcher providers, 2) LLM vision, 3) 2Captcha image task.

        Args:
            image_base64: Base64-encoded PNG/JPEG image data.
            instruction: Natural language instruction for the solver.
            timeout: Maximum wait time.
            start_time: Optionally pass a pre-recorded start time.

        Returns:
            SolverResult with token=recognized text.
        """
        start = start_time or time.time()

        # Try dispatcher first
        if self.dispatcher:
            try:
                from cf_bypass.solvers.dispatcher import CaptchaType
                result = await self.dispatcher.solve(
                    image_base64,
                    CaptchaType.IMAGE,
                    sitekey=instruction,
                    url="",
                    timeout=timeout,
                )
                if result.success:
                    return result
            except Exception as exc:
                logger.debug(f"Dispatcher image solve failed: {exc}")

        # Try LLM vision
        if self.llm_provider:
            try:
                result = await self.llm_provider.solve_image(
                    image_base64,
                    instruction=instruction,
                    timeout=timeout,
                )
                if result.success:
                    return SolverResult(
                        token=result.token,
                        success=True,
                        duration=time.time() - start,
                    )
            except Exception as exc:
                logger.debug(f"LLM vision solve failed: {exc}")

        return SolverResult(
            success=False,
            duration=time.time() - start,
            error="All image captcha solvers exhausted",
        )

    # ------------------------------------------------------------------
    # Convenience: solve with a specific remote provider
    # ------------------------------------------------------------------

    async def solve_with_2captcha(
        self,
        image_base64: str,
        instruction: str = "",
        api_key: str = "",
        timeout: int = 120,
    ) -> SolverResult:
        """Solve an image captcha via 2Captcha directly."""
        from cf_bypass.solvers.providers.twocaptcha import TwoCaptchaProvider

        provider = TwoCaptchaProvider(api_key=api_key)
        result = await provider.solve_image(
            image_base64,
            instruction=instruction,
            timeout=timeout,
        )
        return SolverResult(
            token=result.token,
            success=result.success,
            duration=result.duration,
            error=result.error,
        )

"""LLM Vision provider for image-based CAPTCHA solving.

Uses multimodal LLMs (OpenAI GPT-4V, Anthropic Claude, etc.) to
recognize text in CAPTCHA images. This is a fallback provider —
API-based services (capsolver, 2captcha) should be tried first.
"""

import base64
import time
from typing import Optional

import httpx

from cf_bypass.solvers.providers.base import BaseProvider, ProviderResult
from cf_bypass.solvers.providers import register_provider
from cf_bypass.logging_config import get_logger

logger = get_logger("solvers.llm_vision")

# Provider API endpoints
OPENAI_API = "https://api.openai.com/v1/chat/completions"
ANTHROPIC_API = "https://api.anthropic.com/v1/messages"


@register_provider("llm_vision")
class LLMVisionProvider(BaseProvider):
    """LLM-based image CAPTCHA solver.

    Supports OpenAI (GPT-4V) and Anthropic (Claude) as backends.
    This is an OPTIONAL provider — use only as a fallback after
    dedicated CAPTCHA services.

    Usage::

        provider = LLMVisionProvider(
            provider="openai",
            api_key="sk-...",
            model="gpt-4o",
        )
        result = await provider.solve_image(img_base64, "Type the text")
    """

    def __init__(
        self,
        api_key: str = "",
        provider: str = "openai",
        model: str = "",
    ):
        self.api_key = api_key
        self.llm_provider = provider  # "openai" | "anthropic"
        self.model = model or (
            "gpt-4o" if provider == "openai" else "claude-sonnet-4-20250514"
        )

    @property
    def name(self) -> str:
        return "llm_vision"

    # ------------------------------------------------------------------
    # CAPTCHA solving (only image captcha is supported by LLM)
    # ------------------------------------------------------------------

    async def solve_turnstile(self, sitekey, page_url, timeout=120):
        return ProviderResult(
            success=False,
            error="LLM vision cannot solve Turnstile",
            provider_name=self.name,
        )

    async def solve_recaptcha_v2(self, sitekey, page_url, is_invisible=False, timeout=120):
        return ProviderResult(
            success=False,
            error="LLM vision cannot solve reCAPTCHA v2",
            provider_name=self.name,
        )

    async def solve_recaptcha_v3(self, sitekey, page_url, action="verify", min_score=0.9, timeout=120):
        return ProviderResult(
            success=False,
            error="LLM vision cannot solve reCAPTCHA v3",
            provider_name=self.name,
        )

    async def solve_hcaptcha(self, sitekey, page_url, timeout=120):
        return ProviderResult(
            success=False,
            error="LLM vision cannot solve hCaptcha",
            provider_name=self.name,
        )

    async def solve_image(
        self,
        image_base64: str,
        instruction: str = "Type the characters in the image",
        timeout: int = 60,
    ) -> ProviderResult:
        """Recognize text/objects in a CAPTCHA image using an LLM.

        Args:
            image_base64: Base64-encoded image (without data URI prefix).
            instruction: What to look for in the image.
            timeout: Maximum wait time in seconds.
        """
        if not self.api_key:
            return ProviderResult(
                success=False,
                error=f"No API key configured for {self.llm_provider}",
                provider_name=self.name,
            )

        start = time.time()

        try:
            if self.llm_provider == "openai":
                text = await self._call_openai(image_base64, instruction, timeout)
            elif self.llm_provider == "anthropic":
                text = await self._call_anthropic(image_base64, instruction, timeout)
            else:
                return ProviderResult(
                    success=False,
                    error=f"Unknown LLM provider: {self.llm_provider}",
                    provider_name=self.name,
                )

            duration = time.time() - start

            if text:
                # Clean up common LLM verbosity
                text = text.strip().strip('"').strip("'")
                logger.info(f"LLM vision solved: '{text[:30]}...' in {duration:.1f}s")
                return ProviderResult(
                    token=text,
                    success=True,
                    duration=round(duration, 2),
                    provider_name=self.name,
                )

            return ProviderResult(
                success=False,
                duration=round(duration, 2),
                error="LLM returned empty response",
                provider_name=self.name,
            )

        except Exception as exc:
            logger.debug(f"LLM vision error: {exc}")
            return ProviderResult(
                success=False,
                duration=time.time() - start,
                error=str(exc),
                provider_name=self.name,
            )

    # ------------------------------------------------------------------
    # OpenAI API
    # ------------------------------------------------------------------

    async def _call_openai(
        self,
        image_base64: str,
        instruction: str,
        timeout: int,
    ) -> Optional[str]:
        """Send image to OpenAI GPT-4V."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        # Add data URI prefix if needed
        if not image_base64.startswith("data:"):
            image_url = f"data:image/png;base64,{image_base64}"
        else:
            image_url = image_base64

        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a CAPTCHA solver. Extract ONLY the text/characters "
                        "from the image. Return ONLY the answer, no explanation, "
                        "no punctuation, no extra words."
                    ),
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": image_url, "detail": "low"},
                        },
                        {
                            "type": "text",
                            "text": instruction,
                        },
                    ],
                },
            ],
            "max_tokens": 50,
            "temperature": 0,
        }

        async with httpx.AsyncClient(timeout=float(timeout)) as client:
            resp = await client.post(OPENAI_API, json=payload, headers=headers)
            data = resp.json()

            if "error" in data:
                logger.warning(f"OpenAI API error: {data['error']}")
                return None

            choices = data.get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content", "")

        return None

    # ------------------------------------------------------------------
    # Anthropic API
    # ------------------------------------------------------------------

    async def _call_anthropic(
        self,
        image_base64: str,
        instruction: str,
        timeout: int,
    ) -> Optional[str]:
        """Send image to Anthropic Claude."""
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }

        # Determine media type
        if image_base64.startswith("data:"):
            # Extract media type from data URI
            media_type = image_base64.split(";")[0].replace("data:", "")
            clean_b64 = image_base64.split(",", 1)[1] if "," in image_base64 else image_base64
        else:
            media_type = "image/png"
            clean_b64 = image_base64

        payload = {
            "model": self.model,
            "max_tokens": 50,
            "system": (
                "You are a CAPTCHA solver. Extract ONLY the text/characters "
                "from the image. Return ONLY the answer, no explanation."
            ),
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": clean_b64,
                            },
                        },
                        {
                            "type": "text",
                            "text": instruction,
                        },
                    ],
                },
            ],
        }

        async with httpx.AsyncClient(timeout=float(timeout)) as client:
            resp = await client.post(ANTHROPIC_API, json=payload, headers=headers)
            data = resp.json()

            if "error" in data:
                logger.warning(f"Anthropic API error: {data['error']}")
                return None

            content = data.get("content", [])
            for block in content:
                if block.get("type") == "text":
                    return block.get("text", "")

        return None

"""Abstract base class for CAPTCHA solving service providers.

Each provider (capsolver, 2captcha, LLM vision, etc.) implements this
interface so the CaptchaDispatcher can route tasks uniformly.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ProviderResult:
    """Standard result from a CAPTCHA service provider.

    Attributes:
        token: The solved captcha response token.
        success: Whether the provider returned a valid solution.
        duration: Wall-clock time spent in seconds.
        error: Human-readable error message on failure.
        provider_name: Which provider produced this result.
        raw_response: Optional raw API response for debugging.
        cost_estimate: Estimated cost in USD (if provider reports it).
    """

    token: Optional[str] = None
    success: bool = False
    duration: float = 0.0
    error: Optional[str] = None
    provider_name: str = ""
    raw_response: Optional[dict] = None
    cost_estimate: float = 0.0


class BaseProvider(ABC):
    """Abstract interface for a CAPTCHA solving service.

    Each concrete provider wraps an external API (capsolver, 2captcha, etc.)
    or a local solver (LLM vision, audio solver, injection mode).

    Usage::

        provider = CapsolverProvider(api_key="CAP-...")
        result = await provider.solve_turnstile(sitekey, url, timeout=120)
        if result.success:
            print(f"Token: {result.token}")
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique provider identifier (e.g. 'capsolver', 'twocaptcha')."""
        ...

    @abstractmethod
    async def solve_turnstile(
        self,
        sitekey: str,
        page_url: str,
        timeout: int = 120,
    ) -> ProviderResult:
        """Solve a Cloudflare Turnstile challenge.

        Args:
            sitekey: The Turnstile sitekey from the page.
            page_url: The URL where the captcha appears.
            timeout: Maximum wait time in seconds.

        Returns:
            ProviderResult with token on success.
        """
        ...

    @abstractmethod
    async def solve_recaptcha_v2(
        self,
        sitekey: str,
        page_url: str,
        is_invisible: bool = False,
        timeout: int = 120,
    ) -> ProviderResult:
        """Solve a Google reCAPTCHA v2 challenge.

        Args:
            sitekey: The reCAPTCHA sitekey.
            page_url: The page URL.
            is_invisible: Whether this is an invisible reCAPTCHA.
            timeout: Maximum wait time.

        Returns:
            ProviderResult with g-recaptcha-response on success.
        """
        ...

    @abstractmethod
    async def solve_recaptcha_v3(
        self,
        sitekey: str,
        page_url: str,
        action: str = "verify",
        min_score: float = 0.9,
        timeout: int = 120,
    ) -> ProviderResult:
        """Solve a Google reCAPTCHA v3 challenge (score-based).

        Args:
            sitekey: The reCAPTCHA v3 sitekey.
            page_url: The page URL.
            action: The action name for scoring.
            min_score: Minimum acceptable score (0.0-1.0).
            timeout: Maximum wait time.

        Returns:
            ProviderResult with g-recaptcha-response on success.
        """
        ...

    @abstractmethod
    async def solve_hcaptcha(
        self,
        sitekey: str,
        page_url: str,
        timeout: int = 120,
    ) -> ProviderResult:
        """Solve an hCaptcha challenge.

        Args:
            sitekey: The hCaptcha sitekey.
            page_url: The page URL.
            timeout: Maximum wait time.

        Returns:
            ProviderResult with h-captcha-response on success.
        """
        ...

    async def solve_image(
        self,
        image_base64: str,
        instruction: str = "",
        timeout: int = 60,
    ) -> ProviderResult:
        """Solve a generic image captcha (optional override).

        Not all providers support this — default returns failure.
        """
        return ProviderResult(
            success=False,
            error=f"Image captcha solving not supported by {self.name}",
            provider_name=self.name,
        )

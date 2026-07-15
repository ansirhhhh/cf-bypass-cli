"""Base strategy interface and result types."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, Dict


@dataclass
class BypassResult:
    """Standard result returned by every bypass strategy.

    Attributes:
        success: Whether the strategy completed without throwing an exception.
                 Note: success=True does NOT mean the bypass succeeded — check
                 is_bypass_successful() for challenge-detection logic.
        html: Page HTML content, if available.
        cookies: Extracted cookies (cf_clearance, __cf_bm, etc.).
        strategy_name: Human-readable strategy identifier.
        level: Strategy priority level (1-4).
        duration: Wall-clock time spent in seconds.
        error: Error message if success=False.
        status_code: HTTP response status code.
        challenge_detected: Whether a Cloudflare challenge was detected.
        challenge_type: Type of challenge detected ("turnstile", etc.).
        manual_intervention_needed: Whether user needs to manually solve.
    """

    success: bool
    html: Optional[str] = None
    cookies: Dict[str, str] = field(default_factory=dict)
    strategy_name: str = ""
    level: int = 0
    duration: float = 0.0
    error: Optional[str] = None
    status_code: Optional[int] = None
    challenge_detected: bool = False
    challenge_type: Optional[str] = None
    manual_intervention_needed: bool = False


class BaseStrategy(ABC):
    """All bypass strategies implement this async interface.

    The common async contract allows the orchestrator to iterate strategies
    uniformly without caring about sync/async differences.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable strategy name (e.g. 'cloudscraper')."""
        ...

    @property
    @abstractmethod
    def level(self) -> int:
        """Priority level (1-4). Lower values are tried first."""
        ...

    @abstractmethod
    async def bypass(
        self,
        url: str,
        proxy: Optional[str] = None,
        timeout: int = 60,
        headless: bool = False,
        existing_cookies: Optional[Dict[str, str]] = None,
        keep_open: bool = False,
    ) -> BypassResult:
        """Attempt to bypass Cloudflare protection.

        Args:
            url: Target URL.
            proxy: Optional proxy URL (http://user:pass@host:port).
            timeout: Request timeout in seconds.
            headless: Whether to run browser in headless mode (L3/L4 only).
            existing_cookies: Pre-existing cookies to inject for a refresh attempt.
            keep_open: If True, browser strategies (L3/L4) keep the browser
                       window open after returning (useful for headed mode).

        Returns:
            BypassResult with status, HTML content, and extracted cookies.
        """
        ...

    async def cleanup(self) -> None:
        """Release any persistent resources (browser pools, etc.).

        Override in strategies that hold long-lived resources.
        Default no-op.
        """
        pass

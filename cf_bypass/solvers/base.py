"""Base solver interface and result types."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SolverResult:
    """Result returned by a captcha solver provider.

    Attributes:
        token: The solved captcha token (turnstile response).
        success: Whether the solver completed successfully.
        duration: Wall-clock time spent in seconds.
        error: Error message if success=False.
    """

    token: Optional[str] = None
    success: bool = False
    duration: float = 0.0
    error: Optional[str] = None


class BaseSolver(ABC):
    """Abstract interface for captcha solvers.

    Each solver implementation handles a specific challenge type
    (Turnstile, reCAPTCHA, hCaptcha, etc.) and delegates to
    provider-specific APIs.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable solver name (e.g. 'turnstile')."""
        ...

    @abstractmethod
    async def solve(
        self,
        page_or_html,
        sitekey: str,
        url: str,
        timeout: int = 60,
    ) -> SolverResult:
        """Attempt to solve a captcha challenge.

        Args:
            page_or_html: Browser page object (nodriver/playwright) or HTML string.
            sitekey: The captcha sitekey extracted from the page.
            url: The page URL where the captcha appears.
            timeout: Maximum time to wait for a solution in seconds.

        Returns:
            SolverResult with the token on success.
        """
        ...

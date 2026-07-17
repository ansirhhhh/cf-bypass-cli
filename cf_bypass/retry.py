"""Smart retry with exponential backoff and jitter.

Classifies failures as "hard" (permanent, no point retrying) or
"soft" (transient, worth retrying with backoff).

Hard failures: DNS errors, 404s, permanent bans
Soft failures: timeouts, 503s, 429s, connection resets, challenge pages
"""

import asyncio
import random
import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Any, Awaitable

from cf_bypass.logging_config import get_logger

logger = get_logger("retry")


# ======================================================================
# Error classification
# ======================================================================


class ErrorCategory:
    """Categorize errors for retry decisions."""

    # Status codes that indicate transient issues
    SOFT_STATUS_CODES = {429, 500, 502, 503, 504}

    # Status codes that indicate permanent issues
    HARD_STATUS_CODES = {400, 401, 403, 404, 405, 410, 451}

    # Error message substrings that indicate transient issues
    SOFT_ERROR_PATTERNS = [
        "timeout",
        "timed out",
        "connection reset",
        "connection refused",
        "temporary failure",
        "too many requests",
        "rate limit",
        "try again",
        "service unavailable",
        "network",
        "eof",
        "broken pipe",
        "challenge",
        "cf_chl",
        "turnstile",
    ]

    # Error message substrings that indicate permanent issues
    HARD_ERROR_PATTERNS = [
        "dns",
        "name resolution",
        "certificate",
        "ssl",
        "tls",
        "forbidden",
        "unauthorized",
        "not found",
        "blocked",
        "banned",
    ]

    @classmethod
    def is_soft_failure(cls, error: Optional[str] = None, status_code: int = 0) -> bool:
        """Return True if this is a transient (retryable) failure.

        Args:
            error: Error message string.
            status_code: HTTP status code if available.

        Returns:
            True if the failure is likely transient.
        """
        # Check status code
        if status_code in cls.SOFT_STATUS_CODES:
            return True
        if status_code in cls.HARD_STATUS_CODES:
            return False

        # Check error message patterns
        if error:
            error_lower = error.lower()

            # Hard patterns checked first (higher priority)
            for pattern in cls.HARD_ERROR_PATTERNS:
                if pattern in error_lower:
                    return False

            # Soft patterns
            for pattern in cls.SOFT_ERROR_PATTERNS:
                if pattern in error_lower:
                    return True

        # Default: assume soft (safer to retry)
        return True


# ======================================================================
# RetryPolicy
# ======================================================================


@dataclass
class RetryConfig:
    """Configuration for RetryPolicy.

    Attributes:
        max_retries: Maximum retry attempts (0 = no retries).
        base_delay: Base delay in seconds before first retry.
        max_delay: Maximum delay cap in seconds.
        jitter: Jitter fraction (0.0-1.0). Adds randomness to avoid
                thundering herd. 0.2 = ±20% jitter.
        backoff_multiplier: Exponential backoff multiplier (2.0 = doubles each time).
        retry_on_timeout: Retry on asyncio.TimeoutError.
        retry_on_status: Status codes that trigger retry (in addition to SOFT_STATUS_CODES).
    """

    max_retries: int = 3
    base_delay: float = 1.0
    max_delay: float = 30.0
    jitter: float = 0.2
    backoff_multiplier: float = 2.0
    retry_on_timeout: bool = True
    retry_on_status: List[int] = field(default_factory=list)


class RetryPolicy:
    """Execute async operations with exponential backoff and jitter.

    Usage::

        policy = RetryPolicy(RetryConfig(max_retries=3, base_delay=1.0))
        result = await policy.execute(
            lambda: fetch_url("https://example.com"),
            is_success_fn=lambda r: r.status_code == 200,
        )
    """

    def __init__(self, config: Optional[RetryConfig] = None):
        self.config = config or RetryConfig()

    async def execute(
        self,
        fn: Callable[[], Awaitable[Any]],
        is_success_fn: Optional[Callable[[Any], bool]] = None,
        error_extractor: Optional[Callable[[Exception], tuple]] = None,
    ) -> Any:
        """Execute *fn* with retry logic.

        Args:
            fn: Async callable to execute.
            is_success_fn: Optional function to check if result is success.
                           If None, any non-exception result is considered success.
            error_extractor: Optional function to extract (error_msg, status_code)
                             from an exception. Default tries str(exc).

        Returns:
            The result of fn() on success.

        Raises:
            RuntimeError: If all retries are exhausted.
        """
        cfg = self.config
        last_error = None

        for attempt in range(cfg.max_retries + 1):
            try:
                result = await fn()

                # Check if result indicates success
                if is_success_fn is None or is_success_fn(result):
                    if attempt > 0:
                        logger.info(
                            f"Retry succeeded on attempt {attempt + 1}"
                        )
                    return result

                # Result is a failure — check if retryable
                if attempt < cfg.max_retries:
                    status = getattr(result, "status_code", 0)
                    error = getattr(result, "error", "")

                    if ErrorCategory.is_soft_failure(
                        error=str(error), status_code=status
                    ):
                        delay = self._next_delay(attempt)
                        logger.debug(
                            f"Soft failure (attempt {attempt + 1}), "
                            f"retrying in {delay:.1f}s"
                        )
                        await asyncio.sleep(delay)
                        continue

                    # Hard failure — don't retry
                    logger.debug(
                        f"Hard failure (attempt {attempt + 1}), not retrying"
                    )
                    return result  # return the failed result

            except asyncio.TimeoutError as e:
                last_error = e
                if cfg.retry_on_timeout and attempt < cfg.max_retries:
                    delay = self._next_delay(attempt)
                    logger.debug(
                        f"Timeout (attempt {attempt + 1}), "
                        f"retrying in {delay:.1f}s"
                    )
                    await asyncio.sleep(delay)
                    continue
                raise

            except Exception as e:
                last_error = e
                error_str = str(e)

                if ErrorCategory.is_soft_failure(error=error_str):
                    if attempt < cfg.max_retries:
                        delay = self._next_delay(attempt)
                        logger.debug(
                            f"Soft error (attempt {attempt + 1}): "
                            f"{error_str[:80]}, retrying in {delay:.1f}s"
                        )
                        await asyncio.sleep(delay)
                        continue

                # Hard failure or retries exhausted
                logger.debug(
                    f"Hard error (attempt {attempt + 1}): {error_str[:80]}"
                )
                raise

        # All retries exhausted
        raise RuntimeError(
            f"All {cfg.max_retries + 1} attempts failed. "
            f"Last error: {last_error}"
        )

    async def execute_with_fallback(
        self,
        fn: Callable[[], Awaitable[Any]],
        fallback_fn: Callable[[], Awaitable[Any]],
        is_success_fn: Optional[Callable[[Any], bool]] = None,
    ) -> Any:
        """Execute *fn* with retry, falling back to *fallback_fn* on hard failure.

        This is useful for "try primary, fall back to secondary" patterns.
        """
        try:
            return await self.execute(fn, is_success_fn=is_success_fn)
        except Exception:
            logger.info("Primary failed, executing fallback")
            return await fallback_fn()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _next_delay(self, attempt: int) -> float:
        """Calculate the delay for the next retry attempt.

        Uses exponential backoff: base_delay * (backoff_multiplier ^ attempt)
        with random jitter.
        """
        cfg = self.config
        delay = cfg.base_delay * (cfg.backoff_multiplier ** attempt)
        delay = min(delay, cfg.max_delay)

        # Apply jitter: ± jitter%
        if cfg.jitter > 0:
            jitter_amount = delay * cfg.jitter
            delay += random.uniform(-jitter_amount, jitter_amount)

        return max(0.1, delay)

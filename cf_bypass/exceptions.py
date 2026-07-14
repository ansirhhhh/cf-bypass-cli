"""Custom exception hierarchy for cf-bypass-cli."""

from typing import Optional


class CfBypassError(Exception):
    """Base exception for all cf-bypass errors."""
    pass


class StrategyFailedError(CfBypassError):
    """A single strategy failed. Contains which strategy and why."""

    def __init__(self, strategy_name: str, message: str, original: Optional[Exception] = None):
        self.strategy_name = strategy_name
        self.original = original
        super().__init__(f"[{strategy_name}] {message}")


class CookieExpiredError(CfBypassError):
    """Cached cookies are expired or invalid."""
    pass


class BrowserLaunchError(CfBypassError):
    """Browser failed to launch (missing binary, permissions, etc.)."""
    pass


class AllStrategiesFailedError(CfBypassError):
    """All bypass strategies exhausted without success."""

    def __init__(self, url: str, last_error: str):
        self.url = url
        self.last_error = last_error
        super().__init__(f"All strategies failed for {url}: {last_error}")


class ConfigError(CfBypassError):
    """Configuration loading error."""
    pass


class ProxyError(CfBypassError):
    """Proxy connection failed."""
    pass


class TimeoutError(CfBypassError):
    """Operation exceeded timeout."""
    pass

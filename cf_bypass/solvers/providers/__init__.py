"""CAPTCHA solver provider registry.

Provider instances are loaded dynamically from configuration and support
priority-based fallback chains via the CaptchaDispatcher.
"""

from typing import Dict, Optional, Type

from cf_bypass.solvers.providers.base import BaseProvider, ProviderResult


_provider_registry: Dict[str, Type[BaseProvider]] = {}


def register_provider(name: str) -> callable:
    """Decorator to register a provider class by name."""

    def wrapper(cls: Type[BaseProvider]) -> Type[BaseProvider]:
        _provider_registry[name] = cls
        return cls

    return wrapper


def get_provider(name: str) -> Optional[Type[BaseProvider]]:
    """Look up a registered provider class by name."""
    return _provider_registry.get(name)


def list_providers() -> Dict[str, Type[BaseProvider]]:
    """Return all registered provider classes."""
    return dict(_provider_registry)


__all__ = [
    "BaseProvider",
    "ProviderResult",
    "register_provider",
    "get_provider",
    "list_providers",
]

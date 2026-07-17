"""Unified CAPTCHA dispatcher with priority-based provider fallback.

The dispatcher is the central hub for all CAPTCHA solving. It discovers
captcha types on a page, routes them to the correct solver, and handles
fallback chains when a provider fails.

Design principles:
1. Provider-agnostic: solvers work through the dispatcher, not direct API calls.
2. Priority-based fallback: each captcha type has an ordered list of providers.
3. Config-driven: provider selection comes from captcha.yaml / config.
4. Observable: every solve attempt is logged with provider name, duration, cost.
"""

import time
import re
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Any
from pathlib import Path

import yaml

from cf_bypass.solvers.base import SolverResult
from cf_bypass.solvers.providers.base import BaseProvider, ProviderResult
from cf_bypass.solvers.providers import get_provider as _get_provider_class
from cf_bypass.logging_config import get_logger

logger = get_logger("solvers.dispatcher")


# ======================================================================
# Captcha type enum
# ======================================================================


class CaptchaType(str, Enum):
    """Known captcha/challenge types the dispatcher can handle."""

    TURNSTILE = "turnstile"
    RECAPTCHA_V2 = "recaptcha_v2"
    RECAPTCHA_V3 = "recaptcha_v3"
    HCAPTCHA = "hcaptcha"
    IMAGE = "image"
    UNKNOWN = "unknown"


# ======================================================================
# Provider priority config
# ======================================================================


@dataclass
class ProviderEntry:
    """A single provider entry in the fallback chain."""

    name: str  # "capsolver", "2captcha", "injection", "llm_vision"
    api_key: str = ""
    priority: int = 0
    config: Dict[str, Any] = field(default_factory=dict)  # extra params


@dataclass
class DispatcherConfig:
    """Full dispatcher configuration per captcha type.

    Each captcha type has an ordered priority list of providers.
    The dispatcher tries them in order until one succeeds.
    """

    turnstile: List[ProviderEntry] = field(default_factory=list)
    recaptcha_v2: List[ProviderEntry] = field(default_factory=list)
    recaptcha_v3: List[ProviderEntry] = field(default_factory=list)
    hcaptcha: List[ProviderEntry] = field(default_factory=list)
    image: List[ProviderEntry] = field(default_factory=list)

    timeout: int = 120
    max_retries: int = 2

    @classmethod
    def from_dict(cls, data: dict) -> "DispatcherConfig":
        """Parse from a captcha.yaml-style dict."""
        captcha_cfg = data.get("captcha", data)

        def _parse_entries(type_key: str) -> List[ProviderEntry]:
            providers_list = captcha_cfg.get("providers", {}).get(type_key, [])
            api_keys = captcha_cfg.get("api_keys", {})
            entries = []
            for i, entry in enumerate(providers_list):
                if isinstance(entry, str):
                    entries.append(ProviderEntry(
                        name=entry,
                        api_key=api_keys.get(entry, ""),
                        priority=i,
                    ))
                elif isinstance(entry, dict):
                    entries.append(ProviderEntry(
                        name=entry.get("provider", entry.get("name", "")),
                        api_key=entry.get("api_key", api_keys.get(entry.get("provider", ""), "")),
                        priority=entry.get("priority", i),
                        config=entry.get("config", {}),
                    ))
            return sorted(entries, key=lambda e: e.priority)

        return cls(
            turnstile=_parse_entries("turnstile"),
            recaptcha_v2=_parse_entries("recaptcha_v2"),
            recaptcha_v3=_parse_entries("recaptcha_v3"),
            hcaptcha=_parse_entries("hcaptcha"),
            image=_parse_entries("image"),
            timeout=captcha_cfg.get("timeout", 120),
            max_retries=captcha_cfg.get("max_retries", 2),
        )

    @classmethod
    def from_yaml(cls, path: str) -> "DispatcherConfig":
        """Load from a YAML file."""
        p = Path(path)
        if not p.exists():
            logger.warning(f"Captcha config not found at {path}, using defaults")
            return cls()
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        return cls.from_dict(data)

    def get_providers(self, captcha_type: CaptchaType) -> List[ProviderEntry]:
        """Get ordered provider list for a captcha type."""
        mapping = {
            CaptchaType.TURNSTILE: self.turnstile,
            CaptchaType.RECAPTCHA_V2: self.recaptcha_v2,
            CaptchaType.RECAPTCHA_V3: self.recaptcha_v3,
            CaptchaType.HCAPTCHA: self.hcaptcha,
            CaptchaType.IMAGE: self.image,
        }
        return mapping.get(captcha_type, [])


# ======================================================================
# Captcha detection helpers
# ======================================================================


# Sitekey extraction patterns by captcha type
SITEKEY_PATTERNS: Dict[CaptchaType, List[re.Pattern]] = {
    CaptchaType.TURNSTILE: [
        re.compile(r'data-sitekey\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE),
        re.compile(r'sitekey\s*:\s*["\']([^"\']+)["\']', re.IGNORECASE),
    ],
    CaptchaType.RECAPTCHA_V2: [
        re.compile(r'data-sitekey\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE),
        re.compile(r'grecaptcha\.render\s*\(\s*["\']([^"\']+)["\']', re.IGNORECASE),
    ],
    CaptchaType.RECAPTCHA_V3: [
        re.compile(r'data-sitekey\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE),
    ],
    CaptchaType.HCAPTCHA: [
        re.compile(r'data-sitekey\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE),
        re.compile(r'hcaptcha\.render\s*\(\s*["\']([^"\']+)["\']', re.IGNORECASE),
    ],
    CaptchaType.IMAGE: [
        re.compile(r'(?:captcha|verify|challenge)[-_]?image', re.IGNORECASE),
    ],
}

# DOM indicators for each captcha type
CAPTCHA_INDICATORS: Dict[CaptchaType, List[str]] = {
    CaptchaType.TURNSTILE: [
        "challenges.cloudflare.com",
        "cf-turnstile",
        "turnstile",
    ],
    CaptchaType.RECAPTCHA_V2: [
        "recaptcha/api2",
        "g-recaptcha",
        "grecaptcha.render",
    ],
    CaptchaType.RECAPTCHA_V3: [
        "recaptcha/api.js?render=",
        "grecaptcha.ready",
    ],
    CaptchaType.HCAPTCHA: [
        "hcaptcha.com",
        "h-captcha",
        "hcaptcha.render",
    ],
    CaptchaType.IMAGE: [
        'alt="captcha"',
        'alt="CAPTCHA"',
        "captcha-image",
    ],
}


def detect_captcha_types(html: str) -> List[CaptchaType]:
    """Detect which captcha types are present in the page HTML.

    Returns a list ordered by confidence (most confident first).
    """
    if not html:
        return []

    html_lower = html.lower()
    found: List[CaptchaType] = []

    for ct, indicators in CAPTCHA_INDICATORS.items():
        for indicator in indicators:
            if indicator.lower() in html_lower:
                found.append(ct)
                break

    return found


def extract_sitekey(html: str, captcha_type: CaptchaType) -> Optional[str]:
    """Extract the sitekey for a specific captcha type from HTML."""
    if not html:
        return None

    patterns = SITEKEY_PATTERNS.get(captcha_type, [])
    for pattern in patterns:
        m = pattern.search(html)
        if m and m.lastindex and m.lastindex >= 1:
            return m.group(1)

    return None


# ======================================================================
# CaptchaDispatcher
# ======================================================================


class CaptchaDispatcher:
    """Unified CAPTCHA solving with priority-based provider fallback.

    Usage::

        config = DispatcherConfig.from_dict(captcha_yaml)
        dispatcher = CaptchaDispatcher(config)

        # Auto-detect and solve
        html = await page.get_content()
        result = await dispatcher.detect_and_solve(page, html, url)

        # Or solve a specific type
        result = await dispatcher.solve(
            page, CaptchaType.TURNSTILE,
            sitekey="...", url="https://..."
        )
    """

    def __init__(self, config: DispatcherConfig):
        self.config = config
        self._provider_cache: Dict[str, BaseProvider] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def detect_and_solve(
        self,
        page_or_html,
        url: str,
        timeout: Optional[int] = None,
    ) -> SolverResult:
        """Auto-detect captcha type and solve with best available provider.

        This is the primary entry point for the orchestrator. It:
        1. Gets page HTML
        2. Detects captcha types present
        3. For each type found, tries providers in priority order
        4. Returns the first successful result

        Args:
            page_or_html: Browser page object or HTML string.
            url: The page URL (used as context for API providers).
            timeout: Override default timeout.

        Returns:
            SolverResult with token and metadata on success.
        """
        timeout = timeout or self.config.timeout

        # Get HTML
        if isinstance(page_or_html, str):
            html = page_or_html
        elif hasattr(page_or_html, "get_content"):
            try:
                html = await page_or_html.get_content()
            except Exception as exc:
                logger.debug(f"Failed to get page content: {exc}")
                html = ""
        elif hasattr(page_or_html, "content"):
            try:
                html = await page_or_html.content()
            except Exception as exc:
                logger.debug(f"Failed to get page content: {exc}")
                html = ""
        else:
            return SolverResult(
                success=False,
                error="Invalid page_or_html argument",
            )

        # Detect captcha type(s)
        captcha_types = detect_captcha_types(html)
        if not captcha_types:
            logger.debug("No captcha type detected in page HTML")
            return SolverResult(
                success=False,
                error="No captcha detected on page",
            )

        logger.info(
            f"Captcha types detected: {[ct.value for ct in captcha_types]}"
        )

        # Try each type in order
        last_error = None
        for ct in captcha_types:
            sitekey = extract_sitekey(html, ct) or ""
            result = await self.solve(
                page_or_html, ct,
                sitekey=sitekey, url=url, timeout=timeout,
            )
            if result.success:
                return result
            last_error = result.error

        return SolverResult(
            success=False,
            error=last_error or "All captcha types failed",
        )

    async def solve(
        self,
        page_or_html,
        captcha_type: CaptchaType,
        sitekey: str = "",
        url: str = "",
        timeout: Optional[int] = None,
    ) -> SolverResult:
        """Solve a specific captcha type with provider fallback.

        Tries each configured provider in priority order. On first
        success, returns immediately. On failure, logs and tries the
        next provider.

        Args:
            page_or_html: Browser page object or HTML string.
            captcha_type: Which type of captcha to solve.
            sitekey: The captcha sitekey (auto-extracted if empty).
            url: Page URL for API context.
            timeout: Override default timeout.

        Returns:
            SolverResult on first success, or the last error.
        """
        timeout = timeout or self.config.timeout
        providers = self.config.get_providers(captcha_type)

        if not providers:
            return SolverResult(
                success=False,
                error=f"No providers configured for {captcha_type.value}",
            )

        # Auto-extract sitekey from HTML if not provided
        if not sitekey and not isinstance(page_or_html, str):
            try:
                if hasattr(page_or_html, "get_content"):
                    html = await page_or_html.get_content()
                elif hasattr(page_or_html, "content"):
                    html = await page_or_html.content()
                else:
                    html = ""
                sitekey = extract_sitekey(html, captcha_type) or ""
            except Exception:
                pass

        # Try providers in priority order
        last_error = None
        for attempt, entry in enumerate(providers):
            provider = self._get_or_create_provider(entry)

            if not provider:
                logger.debug(f"Provider '{entry.name}' not available, skipping")
                continue

            try:
                logger.info(
                    f"Solving {captcha_type.value} with {entry.name} "
                    f"(attempt {attempt + 1}/{len(providers)})"
                )

                provider_result = await self._dispatch_to_provider(
                    provider, captcha_type, sitekey, url, timeout
                )

                if provider_result.success:
                    logger.info(
                        f"✓ {captcha_type.value} solved by {entry.name} "
                        f"in {provider_result.duration:.1f}s"
                    )
                    return SolverResult(
                        token=provider_result.token,
                        success=True,
                        duration=provider_result.duration,
                    )

                last_error = provider_result.error or f"{entry.name} returned no token"
                logger.warning(
                    f"✗ {entry.name} failed for {captcha_type.value}: {last_error}"
                )

            except Exception as exc:
                last_error = str(exc)
                logger.warning(f"✗ {entry.name} crashed: {exc}")

        return SolverResult(
            success=False,
            error=f"All providers exhausted. Last error: {last_error}",
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _dispatch_to_provider(
        self,
        provider: BaseProvider,
        captcha_type: CaptchaType,
        sitekey: str,
        url: str,
        timeout: int,
    ) -> ProviderResult:
        """Route a solve request to the correct provider method."""
        dispatch_map = {
            CaptchaType.TURNSTILE: lambda: provider.solve_turnstile(
                sitekey, url, timeout=timeout
            ),
            CaptchaType.RECAPTCHA_V2: lambda: provider.solve_recaptcha_v2(
                sitekey, url, timeout=timeout
            ),
            CaptchaType.RECAPTCHA_V3: lambda: provider.solve_recaptcha_v3(
                sitekey, url, timeout=timeout
            ),
            CaptchaType.HCAPTCHA: lambda: provider.solve_hcaptcha(
                sitekey, url, timeout=timeout
            ),
            CaptchaType.IMAGE: lambda: provider.solve_image(
                "", timeout=timeout
            ),
        }

        handler = dispatch_map.get(captcha_type)
        if handler is None:
            return ProviderResult(
                success=False,
                error=f"Provider {provider.name} cannot solve {captcha_type.value}",
                provider_name=provider.name,
            )

        return await handler()

    def _get_or_create_provider(
        self, entry: ProviderEntry
    ) -> Optional[BaseProvider]:
        """Get or instantiate a provider from a config entry.

        Caches provider instances by name for reuse within a session.
        """
        if entry.name in self._provider_cache:
            return self._provider_cache[entry.name]

        # Special handling for "injection" — not a real provider
        if entry.name == "injection":
            return None  # handled directly by TurnstileSolver

        provider_cls = _get_provider_class(entry.name)
        if provider_cls is None:
            logger.warning(f"Unknown provider: {entry.name}")
            return None

        try:
            # Pass api_key + any extra config
            instance = provider_cls(
                api_key=entry.api_key,
                **entry.config,
            )
            self._provider_cache[entry.name] = instance
            return instance
        except Exception as exc:
            logger.warning(f"Failed to create provider '{entry.name}': {exc}")
            return None

    def clear_provider_cache(self) -> None:
        """Clear cached provider instances (useful for testing)."""
        self._provider_cache.clear()

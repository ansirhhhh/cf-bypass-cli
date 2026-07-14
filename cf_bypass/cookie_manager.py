"""Cookie persistence manager.

Stores Cloudflare clearance cookies per domain as JSON files under
~/.cf-bypass/cookies/.  Handles expiry validation and test-request
confirmation to avoid stale-cookie reuse.

Storage format (one JSON file per domain):
{
    "domain": "example.com",
    "cookies": {"cf_clearance": "...", "__cf_bm": "..."},
    "created_at": "2026-07-14T10:00:00+00:00",
    "expires_at": "2026-07-15T10:00:00+00:00",
    "user_agent": "Mozilla/5.0 ...",
    "last_used": "2026-07-14T10:30:00+00:00"
}
"""

import json
import os
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, List

import httpx

from cf_bypass.logging_config import get_logger

logger = get_logger("cookie_manager")

# Cloudflare clearance tokens typically last 24 hours
CF_COOKIE_TTL_HOURS = 24

# Indicators that a response is still a challenge page
CF_CHALLENGE_INDICATORS = [
    "just a moment",
    "checking your browser",
    "cf-browser-verification",
    "challenge-platform",
    "attention required",
    "cloudflare ray id",
    "/cdn-cgi/challenge-platform",
    "enable javascript and cookies to continue",
]


class CookieManager:
    """Domain-scoped cookie persistence and validation.

    Each domain gets its own JSON file.  Methods are async throughout
    so the orchestrator can call them without thread-pool gymnastics.
    """

    def __init__(self, storage_path: str = "~/.cf-bypass/cookies"):
        self.storage_dir = Path(storage_path).expanduser()
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    #  Path helpers
    # ------------------------------------------------------------------

    def _domain_to_path(self, domain: str) -> Path:
        """Convert a domain name to a safe filesystem path."""
        safe_name = domain.replace(".", "_").replace(":", "_")
        return self.storage_dir / f"{safe_name}.json"

    # ------------------------------------------------------------------
    #  Read / validate
    # ------------------------------------------------------------------

    async def get_valid_cookies(self, domain: str) -> Optional[Dict[str, str]]:
        """Return non-expired cookies for *domain*, or None.

        Checks the ``expires_at`` field against current UTC time.
        A None return means "no usable cache" — the orchestrator should
        fall through to the strategy chain.
        """
        cookie_path = self._domain_to_path(domain)
        if not cookie_path.exists():
            logger.debug(f"No cookie file for {domain}")
            return None

        try:
            data = json.loads(cookie_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning(f"Corrupted cookie file for {domain}: {exc}")
            return None

        # Check expiry
        try:
            expires = datetime.fromisoformat(data["expires_at"])
        except (KeyError, ValueError):
            logger.warning(f"Missing or invalid expires_at for {domain}")
            return None

        if datetime.now(timezone.utc) >= expires:
            logger.info(f"Cookies for {domain} expired at {expires.isoformat()}")
            return None

        return data.get("cookies")

    async def validate_cookies(
        self,
        domain: str,
        cookies: Dict[str, str],
        url: Optional[str] = None,
        proxy: Optional[str] = None,
    ) -> bool:
        """Make a test request to confirm cookies still bypass protection.

        Sends a GET to ``url`` (or ``https://{domain}/``) with the cookies
        injected.  Returns True only when the response is 200 and does NOT
        contain Cloudflare challenge indicators.

        This is the definitive check — CF can revoke a ``cf_clearance``
        token before its nominal expiry.
        """
        test_url = url or f"https://{domain}/"

        client_kwargs: dict = {
            "cookies": cookies,
            "timeout": 15.0,
            "follow_redirects": True,
        }
        if proxy:
            client_kwargs["proxies"] = proxy

        try:
            async with httpx.AsyncClient(**client_kwargs) as client:
                response = await client.get(test_url)

                if response.status_code != 200:
                    logger.debug(
                        f"Cookie validation for {domain}: status={response.status_code}"
                    )
                    return False

                text_lower = response.text.lower()
                for indicator in CF_CHALLENGE_INDICATORS:
                    if indicator in text_lower:
                        logger.debug(
                            f"Cookie validation for {domain}: challenge indicator "
                            f"'{indicator}' found"
                        )
                        return False

                logger.debug(f"Cookie validation for {domain}: OK")
                return True

        except Exception as exc:
            logger.debug(f"Cookie validation request failed for {domain}: {exc}")
            return False

    # ------------------------------------------------------------------
    #  Write
    # ------------------------------------------------------------------

    async def store(
        self,
        domain: str,
        cookies: Dict[str, str],
        user_agent: str = "",
    ) -> None:
        """Persist cookies with expiry metadata.

        Expiry is set to now + CF_COOKIE_TTL_HOURS (default 24 h).
        """
        now = datetime.now(timezone.utc)
        expires = now + timedelta(hours=CF_COOKIE_TTL_HOURS)

        data = {
            "domain": domain,
            "cookies": cookies,
            "created_at": now.isoformat(),
            "expires_at": expires.isoformat(),
            "user_agent": user_agent,
            "last_used": now.isoformat(),
        }

        cookie_path = self._domain_to_path(domain)
        cookie_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info(f"Stored {len(cookies)} cookies for {domain}")

    async def update_last_used(self, domain: str) -> None:
        """Bump the ``last_used`` timestamp (does not extend expiry)."""
        cookie_path = self._domain_to_path(domain)
        if not cookie_path.exists():
            return

        try:
            data = json.loads(cookie_path.read_text(encoding="utf-8"))
            data["last_used"] = datetime.now(timezone.utc).isoformat()
            cookie_path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except (json.JSONDecodeError, KeyError, OSError) as exc:
            logger.warning(f"Failed to update last_used for {domain}: {exc}")

    # ------------------------------------------------------------------
    #  List / clear
    # ------------------------------------------------------------------

    async def list_all(self) -> List[Dict]:
        """Return summary rows for every stored cookie file.

        Each row: {domain, cookie_count, created_at, expires_at, last_used,
        has_cf_clearance}.
        """
        results: List[Dict] = []
        for file_path in sorted(self.storage_dir.glob("*.json")):
            try:
                data = json.loads(file_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                logger.warning(f"Skipping corrupted file: {file_path.name}")
                continue

            results.append({
                "domain": data.get("domain", file_path.stem),
                "cookie_count": len(data.get("cookies", {})),
                "created_at": data.get("created_at", ""),
                "expires_at": data.get("expires_at", ""),
                "last_used": data.get("last_used", ""),
                "has_cf_clearance": "cf_clearance" in data.get("cookies", {}),
            })
        return results

    async def clear_all(self) -> int:
        """Delete all cookie JSON files.  Returns count of removed files."""
        count = 0
        for file_path in self.storage_dir.glob("*.json"):
            try:
                file_path.unlink()
                count += 1
            except OSError as exc:
                logger.warning(f"Failed to delete {file_path}: {exc}")
        logger.info(f"Cleared {count} cookie file(s)")
        return count

    async def clear_domain(self, domain: str) -> bool:
        """Remove the cookie file for a single domain.  Returns True if deleted."""
        cookie_path = self._domain_to_path(domain)
        if cookie_path.exists():
            try:
                cookie_path.unlink()
                logger.info(f"Cleared cookies for {domain}")
                return True
            except OSError as exc:
                logger.error(f"Failed to clear cookies for {domain}: {exc}")
                return False
        return False

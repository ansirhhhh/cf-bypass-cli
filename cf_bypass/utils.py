"""Utility functions for cf-bypass-cli."""

import re
from urllib.parse import urlparse


def extract_domain(url: str) -> str:
    """Extract domain (netloc) from a URL.

    Handles URLs with and without scheme.

    >>> extract_domain("https://example.com/path")
    'example.com'
    >>> extract_domain("example.com:8080/path")
    'example.com'
    >>> extract_domain("https://sub.example.co.uk/path?q=1")
    'sub.example.co.uk'
    """
    if not re.match(r"^https?://", url, re.IGNORECASE):
        url = "https://" + url
    parsed = urlparse(url)
    hostname = parsed.hostname or parsed.netloc.split(":")[0]
    return hostname


def normalize_url(url: str) -> str:
    """Ensure URL has a scheme prepended.

    >>> normalize_url("example.com")
    'https://example.com'
    >>> normalize_url("https://example.com")
    'https://example.com'
    """
    url = url.strip()
    if not re.match(r"^https?://", url, re.IGNORECASE):
        url = "https://" + url
    return url


def is_valid_url(url: str) -> bool:
    """Check if string looks like a valid HTTP(S) URL."""
    try:
        if "://" in url:
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https"):
                return False
        else:
            parsed = urlparse(f"https://{url}")
        return bool(parsed.netloc) and "." in parsed.netloc
    except Exception:
        return False


def sanitize_filename(name: str) -> str:
    """Convert domain name to safe filename."""
    return re.sub(r"[^\w\-.]", "_", name)

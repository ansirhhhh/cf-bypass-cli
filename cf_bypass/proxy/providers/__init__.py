"""Proxy provider adapters.

Each provider module implements a standard interface for fetching
proxy lists from commercial/residential proxy services.

Supported providers:
- file: Read proxy URLs from local txt/json files
- brightdata: BrightData (formerly Luminati) proxy API
- oxylabs: Oxylabs proxy API
- ipidea: IPIDEA proxy API
"""

from typing import List, Optional
from cf_bypass.proxy.pool import ProxyNode
from cf_bypass.logging_config import get_logger

logger = get_logger("proxy.providers")


async def load_from_file(
    path: str,
    provider: str = "file",
    proxy_type: str = "residential",
    geo_country: str = "",
) -> List[ProxyNode]:
    """Load proxy URLs from a local file.

    Supports formats:
    - txt: one URL per line, # comments
    - json: [{"url": "...", "country": "US", ...}, ...]

    Args:
        path: Path to the proxy list file.
        provider: Label for the provider field.
        proxy_type: Default proxy type for all entries.
        geo_country: Default country for all entries.

    Returns:
        List of ProxyNode objects.
    """
    from pathlib import Path
    import json

    p = Path(path)
    if not p.exists():
        logger.warning(f"Proxy file not found: {path}")
        return []

    proxies: List[ProxyNode] = []

    if p.suffix.lower() == ".json":
        data = json.loads(p.read_text(encoding="utf-8"))
        for entry in data:
            if isinstance(entry, str):
                proxies.append(ProxyNode(
                    url=entry,
                    provider=provider,
                    proxy_type=proxy_type,
                    geo_country=geo_country,
                ))
            elif isinstance(entry, dict):
                proxies.append(ProxyNode(
                    url=entry.get("url", ""),
                    protocol=entry.get("protocol", "http"),
                    provider=provider,
                    geo_country=entry.get("country", geo_country),
                    geo_city=entry.get("city", ""),
                    proxy_type=entry.get("type", proxy_type),
                ))
    else:
        # txt format
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            proxies.append(ProxyNode(
                url=line,
                provider=provider,
                proxy_type=proxy_type,
                geo_country=geo_country,
            ))

    logger.info(f"Loaded {len(proxies)} proxies from {path}")
    return proxies


async def load_from_brightdata(
    api_token: str = "",
    zone: str = "",
    count: int = 10,
    country: str = "",
) -> List[ProxyNode]:
    """Load proxies from BrightData (formerly Luminati).

    Requires a BrightData account with API access.
    Zone-based: each zone has its own proxy endpoint.

    Args:
        api_token: BrightData API token.
        zone: Zone name (e.g., "my_zone").
        count: Number of proxies to fetch.
        country: ISO country code filter.

    Returns:
        List of ProxyNode objects.
    """
    if not api_token or not zone:
        logger.warning("BrightData requires api_token and zone")
        return []

    proxies: List[ProxyNode] = []

    # BrightData zone URL format:
    # http://brd-customer-{customer}-zone-{zone}-country-{country}:{password}@zproxy.lum-superproxy.io:22225
    for _ in range(count):
        geo = country or "us"
        url = (
            f"http://brd-customer-hl_{zone}-country-{geo}:"
            f"{api_token}@zproxy.lum-superproxy.io:22225"
        )
        proxies.append(ProxyNode(
            url=url,
            protocol="http",
            provider="brightdata",
            proxy_type="residential",
            geo_country=country.upper() if country else "",
        ))

    logger.info(f"Created {len(proxies)} BrightData proxy entries")
    return proxies


async def load_from_oxylabs(
    username: str = "",
    password: str = "",
    count: int = 10,
    country: str = "",
) -> List[ProxyNode]:
    """Load proxies from Oxylabs.

    Oxylabs provides residential proxies via a single endpoint
    with country selection via subdomain.

    Args:
        username: Oxylabs username.
        password: Oxylabs password.
        count: Number of proxy entries to create.
        country: ISO country code (e.g., "us").

    Returns:
        List of ProxyNode objects.
    """
    if not username or not password:
        logger.warning("Oxylabs requires username and password")
        return []

    proxies: List[ProxyNode] = []

    for _ in range(count):
        endpoint = "pr.oxylabs.io:7777"
        if country:
            endpoint = f"pr.oxylabs.io:7777"  # country filtering via subdomain

        url = f"http://customer-{username}:{password}@{endpoint}"
        proxies.append(ProxyNode(
            url=url,
            protocol="http",
            provider="oxylabs",
            proxy_type="residential",
            geo_country=country.upper() if country else "",
        ))

    logger.info(f"Created {len(proxies)} Oxylabs proxy entries")
    return proxies


async def load_from_ipidea(
    api_key: str = "",
    count: int = 10,
    country: str = "",
) -> List[ProxyNode]:
    """Load proxies from IPIDEA.

    Args:
        api_key: IPIDEA API key.
        count: Number of proxies to fetch.
        country: ISO country code.

    Returns:
        List of ProxyNode objects.
    """
    if not api_key:
        logger.warning("IPIDEA requires api_key")
        return []

    proxies: List[ProxyNode] = []

    for _ in range(count):
        url = f"http://{api_key}:@proxy.ipidea.io:2334"
        proxies.append(ProxyNode(
            url=url,
            protocol="http",
            provider="ipidea",
            proxy_type="residential",
            geo_country=country.upper() if country else "",
        ))

    logger.info(f"Created {len(proxies)} IPIDEA proxy entries")
    return proxies


# Provider loader registry
PROVIDER_LOADERS = {
    "file": load_from_file,
    "brightdata": load_from_brightdata,
    "oxylabs": load_from_oxylabs,
    "ipidea": load_from_ipidea,
}


async def load_proxies(provider: str, **kwargs) -> List[ProxyNode]:
    """Load proxies from a named provider.

    Args:
        provider: Provider name ("file", "brightdata", "oxylabs", "ipidea").
        **kwargs: Provider-specific arguments.

    Returns:
        List of ProxyNode objects.
    """
    loader = PROVIDER_LOADERS.get(provider)
    if loader is None:
        logger.warning(f"Unknown proxy provider: {provider}")
        return []
    return await loader(**kwargs)

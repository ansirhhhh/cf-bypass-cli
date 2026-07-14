"""Batch URL processor.

Reads a text file containing one URL per line, processes each through
the orchestrator, and writes results to a CSV output file.
"""

import csv
import asyncio
from pathlib import Path
from typing import Optional, List, Dict, Any

from cf_bypass.orchestrator import Orchestrator
from cf_bypass.logging_config import get_logger

logger = get_logger("batch")


class BatchProcessor:
    """Process multiple URLs sequentially and produce CSV output.

    Parameters
    ----------
    orchestrator:
        Shared orchestrator instance.  Cookie caching across URLs means
        earlier results can benefit later requests to the same domain.
    max_concurrent:
        Maximum number of concurrent bypass attempts.  Default 1
        (sequential) to avoid resource contention with browsers.
    """

    def __init__(self, orchestrator: Orchestrator, max_concurrent: int = 1):
        self.orchestrator = orchestrator
        self._semaphore = asyncio.Semaphore(max_concurrent)

    # ------------------------------------------------------------------
    #  Public API
    # ------------------------------------------------------------------

    async def process_file(
        self,
        input_path: str,
        output_path: str,
        timeout: int = 60,
        proxy: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Read URLs from *input_path*, bypass each, and write CSV to *output_path*.

        Returns the list of result dicts for programmatic use.
        """
        urls = self._read_urls(input_path)
        if not urls:
            logger.warning(f"No valid URLs found in {input_path}")
            return []

        logger.info(f"Processing {len(urls)} URLs, output to {output_path}")
        results = await self._process_all(urls, timeout=timeout, proxy=proxy)
        self._write_csv(results, output_path)
        return results

    async def process_urls(
        self,
        urls: List[str],
        output_path: str,
        timeout: int = 60,
        proxy: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Bypass a list of URLs and write CSV to *output_path*."""
        logger.info(f"Processing {len(urls)} URLs, output to {output_path}")
        results = await self._process_all(urls, timeout=timeout, proxy=proxy)
        self._write_csv(results, output_path)
        return results

    # ------------------------------------------------------------------
    #  Internals
    # ------------------------------------------------------------------

    def _read_urls(self, path: str) -> List[str]:
        """Extract non-empty, non-comment lines from a file."""
        file_path = Path(path)
        if not file_path.exists():
            logger.error(f"URL file not found: {path}")
            return []

        urls: List[str] = []
        for line in file_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                urls.append(stripped)
        return urls

    async def _process_all(
        self,
        urls: List[str],
        timeout: int = 60,
        proxy: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Process URLs with concurrency control."""
        tasks = [
            self._process_one(url, timeout=timeout, proxy=proxy)
            for url in urls
        ]
        return await asyncio.gather(*tasks)

    async def _process_one(
        self,
        url: str,
        timeout: int = 60,
        proxy: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Bypass a single URL and return a result dict."""
        async with self._semaphore:
            logger.info(f"Processing: {url}")
            result = await self.orchestrator.bypass(
                url=url,
                cookie_only=False,
                proxy=proxy,
                timeout=timeout,
            )
            return {
                "url": url,
                "success": result.success,
                "strategy": result.strategy_name,
                "level": result.level,
                "status_code": result.status_code,
                "duration": round(result.duration, 2),
                "cookies_count": len(result.cookies),
                "has_cf_clearance": "cf_clearance" in {
                    k.lower() for k in result.cookies
                },
                "error": result.error or "",
            }

    # ------------------------------------------------------------------
    #  CSV output
    # ------------------------------------------------------------------

    @staticmethod
    def _write_csv(results: List[Dict[str, Any]], output_path: str) -> None:
        """Write results list to a CSV file."""
        if not results:
            logger.warning("No results to write")
            return

        fieldnames = [
            "url", "success", "strategy", "level", "status_code",
            "duration", "cookies_count", "has_cf_clearance", "error",
        ]

        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        with output_file.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(results)

        logger.info(f"Wrote {len(results)} rows to {output_path}")

"""Bypass metrics data model.

Each bypass attempt generates one BypassMetrics record, persisted
to SQLite for later analysis and dashboard visualization.
"""

import json
import sqlite3
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional
from pathlib import Path

from cf_bypass.logging_config import get_logger

logger = get_logger("observability.metrics")


@dataclass
class BypassMetrics:
    """Structured metrics for a single bypass attempt.

    All fields are captured regardless of success/failure so the
    dashboard can show failure analysis.
    """

    # Request identity
    url: str = ""
    domain: str = ""
    started_at: str = ""  # ISO 8601

    # Timing
    duration_ms: int = 0

    # Strategy
    strategy_used: str = ""
    strategy_level: int = 0

    # Cache
    cache_hit: bool = False

    # Proxy
    proxy_used: str = "none"
    proxy_country: str = ""

    # Challenge
    challenge_detected: bool = False
    challenge_type: Optional[str] = None
    captcha_solved: bool = False
    captcha_solver: Optional[str] = None

    # Fingerprint
    fingerprint_id: str = ""

    # Result
    html_size: int = 0
    cookie_count: int = 0
    final_status_code: int = 0
    error_code: Optional[str] = None

    # v2.0 extras
    smart_routing_used: bool = False
    retry_count: int = 0
    proxy_pool_used: bool = False


# ---------------------------------------------------------------------------
# Async-safe recorder
# ---------------------------------------------------------------------------

_write_lock = threading.Lock()


def record_metrics(metrics: BypassMetrics, db_path: str) -> None:
    """Record a bypass attempt to the metrics database.

    This function is designed to be called from the orchestrator after
    every bypass attempt. It uses a threading lock to ensure thread-safe
    writes and never raises (failures are logged and swallowed).

    Args:
        metrics: The BypassMetrics to record.
        db_path: Path to the SQLite database file.
    """
    if not db_path:
        return

    try:
        # Set timestamp if not already set
        if not metrics.started_at:
            metrics.started_at = datetime.now(timezone.utc).isoformat()

        with _write_lock:
            _write_metrics(metrics, db_path)
    except Exception as exc:
        logger.debug(f"Failed to record metrics (non-fatal): {exc}")


def _write_metrics(metrics: BypassMetrics, db_path: str) -> None:
    """Internal: write a single metrics record to SQLite."""
    db_file = Path(db_path).expanduser()
    db_file.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_file))
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS bypass_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL,
                domain TEXT NOT NULL,
                started_at TEXT NOT NULL,
                duration_ms INTEGER DEFAULT 0,
                strategy_used TEXT DEFAULT '',
                strategy_level INTEGER DEFAULT 0,
                cache_hit INTEGER DEFAULT 0,
                proxy_used TEXT DEFAULT 'none',
                proxy_country TEXT DEFAULT '',
                challenge_detected INTEGER DEFAULT 0,
                challenge_type TEXT,
                captcha_solved INTEGER DEFAULT 0,
                captcha_solver TEXT,
                fingerprint_id TEXT DEFAULT '',
                html_size INTEGER DEFAULT 0,
                cookie_count INTEGER DEFAULT 0,
                final_status_code INTEGER DEFAULT 0,
                error_code TEXT,
                smart_routing_used INTEGER DEFAULT 0,
                retry_count INTEGER DEFAULT 0,
                proxy_pool_used INTEGER DEFAULT 0
            )
        """)

        conn.execute("""
            INSERT INTO bypass_metrics (
                url, domain, started_at, duration_ms,
                strategy_used, strategy_level, cache_hit,
                proxy_used, proxy_country,
                challenge_detected, challenge_type,
                captcha_solved, captcha_solver,
                fingerprint_id,
                html_size, cookie_count, final_status_code, error_code,
                smart_routing_used, retry_count, proxy_pool_used
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            metrics.url,
            metrics.domain,
            metrics.started_at,
            metrics.duration_ms,
            metrics.strategy_used,
            metrics.strategy_level,
            1 if metrics.cache_hit else 0,
            metrics.proxy_used,
            metrics.proxy_country,
            1 if metrics.challenge_detected else 0,
            metrics.challenge_type,
            1 if metrics.captcha_solved else 0,
            metrics.captcha_solver,
            metrics.fingerprint_id,
            metrics.html_size,
            metrics.cookie_count,
            metrics.final_status_code,
            metrics.error_code,
            1 if metrics.smart_routing_used else 0,
            metrics.retry_count,
            1 if metrics.proxy_pool_used else 0,
        ))

        conn.commit()
    finally:
        conn.close()

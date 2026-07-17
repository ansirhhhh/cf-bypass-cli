"""Metrics storage and query interface.

Provides read access to the SQLite metrics database for the CLI
stats command and dashboard.
"""

import sqlite3
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime, timedelta, timezone

from cf_bypass.logging_config import get_logger

logger = get_logger("observability.storage")


class MetricsStorage:
    """Query interface for the bypass metrics database.

    Usage::

        storage = MetricsStorage("~/.cf-bypass/metrics.db")
        summary = storage.get_summary(days=7)
        print(f"MSR: {summary['success_rate']:.1%}")
    """

    def __init__(self, db_path: str = "~/.cf-bypass/metrics.db"):
        self.db_path = str(Path(db_path).expanduser())

    @property
    def exists(self) -> bool:
        return Path(self.db_path).exists()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def get_summary(self, days: int = 7) -> dict:
        """Return summary statistics for the last N days.

        Returns dict with: total_requests, success_count, success_rate,
        avg_duration_ms, cache_hit_rate, top_strategies, top_errors.
        """
        if not self.exists:
            return {"total_requests": 0, "success_count": 0, "success_rate": 0.0}

        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

        conn = self._connect()
        try:
            # Total and success count
            total = conn.execute(
                "SELECT COUNT(*) as c FROM bypass_metrics WHERE started_at >= ?",
                (cutoff,)
            ).fetchone()["c"]

            # Success = got cf_clearance (cookie_count > 0 and no error_code)
            success = conn.execute(
                """SELECT COUNT(*) as c FROM bypass_metrics
                   WHERE started_at >= ? AND cookie_count > 0 AND error_code IS NULL""",
                (cutoff,)
            ).fetchone()["c"]

            # Average duration
            avg_dur = conn.execute(
                "SELECT AVG(duration_ms) as a FROM bypass_metrics WHERE started_at >= ?",
                (cutoff,)
            ).fetchone()["a"] or 0

            # Cache hit rate
            cache_total = conn.execute(
                "SELECT COUNT(*) as c FROM bypass_metrics WHERE started_at >= ? AND cache_hit = 1",
                (cutoff,)
            ).fetchone()["c"]

            # Top strategies
            top_strategies = [
                dict(row) for row in conn.execute(
                    """SELECT strategy_used, COUNT(*) as count
                       FROM bypass_metrics WHERE started_at >= ?
                       GROUP BY strategy_used ORDER BY count DESC LIMIT 5""",
                    (cutoff,)
                ).fetchall()
            ]

            # Top errors
            top_errors = [
                dict(row) for row in conn.execute(
                    """SELECT error_code, COUNT(*) as count
                       FROM bypass_metrics WHERE started_at >= ?
                       AND error_code IS NOT NULL
                       GROUP BY error_code ORDER BY count DESC LIMIT 5""",
                    (cutoff,)
                ).fetchall()
            ]

            return {
                "total_requests": total,
                "success_count": success,
                "success_rate": success / total if total > 0 else 0.0,
                "avg_duration_ms": round(avg_dur, 0),
                "cache_hit_rate": cache_total / total if total > 0 else 0.0,
                "top_strategies": top_strategies,
                "top_errors": top_errors,
                "period_days": days,
            }

        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Per-domain stats
    # ------------------------------------------------------------------

    def get_domain_stats(self, domain: str = "", days: int = 7) -> List[dict]:
        """Return per-domain statistics."""
        if not self.exists:
            return []

        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        conn = self._connect()

        try:
            query = """SELECT domain, COUNT(*) as total,
                              SUM(CASE WHEN cookie_count > 0 AND error_code IS NULL THEN 1 ELSE 0 END) as success,
                              AVG(duration_ms) as avg_duration
                       FROM bypass_metrics WHERE started_at >= ?"""
            params = [cutoff]

            if domain:
                query += " AND domain = ?"
                params.append(domain)

            query += " GROUP BY domain ORDER BY total DESC LIMIT 20"

            return [dict(row) for row in conn.execute(query, params).fetchall()]
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Strategy breakdown
    # ------------------------------------------------------------------

    def get_strategy_stats(self, days: int = 7) -> List[dict]:
        """Return per-strategy success rates."""
        if not self.exists:
            return []

        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        conn = self._connect()

        try:
            rows = conn.execute(
                """SELECT strategy_used, strategy_level,
                          COUNT(*) as total,
                          SUM(CASE WHEN cookie_count > 0 AND error_code IS NULL THEN 1 ELSE 0 END) as success,
                          AVG(duration_ms) as avg_duration
                   FROM bypass_metrics WHERE started_at >= ?
                   GROUP BY strategy_used ORDER BY strategy_level""",
                (cutoff,)
            ).fetchall()

            result = []
            for row in rows:
                d = dict(row)
                d["success_rate"] = d["success"] / d["total"] if d["total"] > 0 else 0
                result.append(d)
            return result
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Time-series (for dashboard charts)
    # ------------------------------------------------------------------

    def get_daily_stats(self, days: int = 30) -> List[dict]:
        """Return daily success rates for trend charts."""
        if not self.exists:
            return []

        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        conn = self._connect()

        try:
            rows = conn.execute(
                """SELECT DATE(started_at) as day,
                          COUNT(*) as total,
                          SUM(CASE WHEN cookie_count > 0 AND error_code IS NULL THEN 1 ELSE 0 END) as success,
                          AVG(duration_ms) as avg_duration
                   FROM bypass_metrics WHERE started_at >= ?
                   GROUP BY day ORDER BY day""",
                (cutoff,)
            ).fetchall()

            result = []
            for row in rows:
                d = dict(row)
                d["success_rate"] = d["success"] / d["total"] if d["total"] > 0 else 0
                result.append(d)
            return result
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def archive_old(self, days: int = 30) -> int:
        """Delete records older than N days. Returns count deleted."""
        if not self.exists:
            return 0

        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        conn = self._connect()

        try:
            cursor = conn.execute(
                "DELETE FROM bypass_metrics WHERE started_at < ?",
                (cutoff,)
            )
            conn.commit()
            deleted = cursor.rowcount
            if deleted > 0:
                logger.info(f"Archived {deleted} old metrics records (> {days}d)")
            return deleted
        finally:
            conn.close()

"""Logging configuration for cf-bypass-cli."""

import logging
import sys
from typing import Optional


_logger_cache: dict[str, logging.Logger] = {}
_initialized: bool = False


def setup_logging(level: str = "INFO") -> None:
    """Configure root logger with structured format."""
    global _initialized
    if _initialized:
        return

    fmt = logging.Formatter(
        fmt="%(asctime)s [%(levelname)-5s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(fmt)

    root = logging.getLogger("cf_bypass")
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.handlers.clear()
    root.addHandler(handler)
    root.propagate = False

    _initialized = True


def get_logger(name: str) -> logging.Logger:
    """Get or create a logger in the cf_bypass namespace."""
    full_name = f"cf_bypass.{name}"
    if full_name not in _logger_cache:
        _logger_cache[full_name] = logging.getLogger(full_name)
    return _logger_cache[full_name]

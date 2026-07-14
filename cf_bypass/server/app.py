"""FastAPI application for cf-bypass-cli serve mode.

Provides an HTTP API that wraps the orchestrator so external tools
(scripts, browser extensions, etc.) can request Cloudflare bypasses
without installing the CLI or its dependencies.
"""

import time
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException

from cf_bypass.config import Config
from cf_bypass.cookie_manager import CookieManager
from cf_bypass.orchestrator import Orchestrator
from cf_bypass.server.models import (
    BypassRequest,
    BypassResponse,
    CookieInfo,
    StatusResponse,
    DeleteResponse,
)
from cf_bypass.logging_config import setup_logging, get_logger

logger = get_logger("server")

# ---------------------------------------------------------------------------
#  Shared server state
# ---------------------------------------------------------------------------


class _ServerState:
    """Mutable singleton holding the orchestrator and its dependencies."""

    def __init__(self) -> None:
        self.orchestrator: Optional[Orchestrator] = None
        self.config: Optional[Config] = None
        self.cookie_manager: Optional[CookieManager] = None


_state = _ServerState()

# ---------------------------------------------------------------------------
#  Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Startup / shutdown lifecycle for the FastAPI app."""
    setup_logging("INFO")
    logger.info("Starting cf-bypass API server")

    # Only initialize if not already set (allows test injection)
    if _state.orchestrator is None:
        _state.config = Config.load()
        _state.cookie_manager = CookieManager(_state.config.storage_path)
        _state.orchestrator = Orchestrator(_state.cookie_manager, _state.config)

    yield  # <-- server runs here

    logger.info("Shutting down cf-bypass API server")
    if _state.orchestrator is not None:
        await _state.orchestrator.shutdown()


# ---------------------------------------------------------------------------
#  Endpoint implementations (must be defined before create_app / module-level app)
# ---------------------------------------------------------------------------


async def _bypass_endpoint(req: BypassRequest) -> BypassResponse:
    """Bypass Cloudflare protection for a URL."""
    if _state.orchestrator is None:
        raise HTTPException(status_code=503, detail="Server not initialized")

    start = time.time()
    result = await _state.orchestrator.bypass(
        url=req.url,
        cookie_only=req.cookie_only,
        proxy=req.proxy,
        timeout=req.timeout,
    )
    duration = round(time.time() - start, 2)

    if not result.success:
        return BypassResponse(
            status="error",
            duration=duration,
            error=result.error,
        )

    return BypassResponse(
        status="success",
        cookies=result.cookies,
        html=result.html if not req.cookie_only else None,
        duration=duration,
    )


async def _health_check() -> dict:
    """Health check endpoint."""
    return {"status": "ok", "service": "cf-bypass-cli"}


async def _list_cookies() -> StatusResponse:
    """List all stored cookies."""
    if _state.cookie_manager is None:
        raise HTTPException(status_code=503, detail="Server not initialized")

    rows = await _state.cookie_manager.list_all()
    domains = [
        CookieInfo(
            domain=r["domain"],
            cookie_count=r["cookie_count"],
            created_at=r["created_at"],
            expires_at=r["expires_at"],
            last_used=r["last_used"],
            has_cf_clearance=r["has_cf_clearance"],
        )
        for r in rows
    ]
    return StatusResponse(domains=domains, total=len(domains))


async def _delete_cookies(domain: str) -> DeleteResponse:
    """Delete stored cookies for a specific domain."""
    if _state.cookie_manager is None:
        raise HTTPException(status_code=503, detail="Server not initialized")

    deleted = await _state.cookie_manager.clear_domain(domain)
    if not deleted:
        raise HTTPException(
            status_code=404, detail=f"No cookies found for {domain}"
        )
    return DeleteResponse(status="deleted", domain=domain)


# ---------------------------------------------------------------------------
#  App factory
# ---------------------------------------------------------------------------


def create_app(config: Optional[Config] = None) -> FastAPI:
    """Create and configure a FastAPI application instance.

    If *config* is provided, it replaces the default Config.load().
    """
    if config is not None:
        _state.config = config
        _state.cookie_manager = CookieManager(config.storage_path)
        _state.orchestrator = Orchestrator(_state.cookie_manager, config)

    app = FastAPI(
        title="cf-bypass-cli",
        description="Progressive Cloudflare WAF bypass API",
        version="0.1.0",
        lifespan=_lifespan,
    )

    # Register routes
    app.post("/bypass", response_model=BypassResponse)(_bypass_endpoint)
    app.get("/health")(_health_check)
    app.get("/cookies", response_model=StatusResponse)(_list_cookies)
    app.delete("/cookies/{domain}", response_model=DeleteResponse)(_delete_cookies)

    return app


# Pre-built app instance used by ``cf-bypass serve``
app = create_app()

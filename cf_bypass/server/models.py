"""Pydantic request / response models for the HTTP API."""

from typing import Optional, Dict, List

from pydantic import BaseModel, Field


class BypassRequest(BaseModel):
    """Request body for POST /bypass."""

    url: str = Field(..., description="Target URL to bypass")
    cookie_only: bool = Field(
        False, description="Return cookies only, omit HTML from response"
    )
    timeout: int = Field(
        60, ge=1, le=300, description="Timeout in seconds"
    )
    proxy: Optional[str] = Field(
        None, description="Optional proxy URL (http://user:pass@host:port)"
    )


class CookieInfo(BaseModel):
    """Summary of stored cookies for one domain."""

    domain: str
    cookie_count: int
    created_at: str
    expires_at: str
    last_used: str
    has_cf_clearance: bool


class BypassResponse(BaseModel):
    """Response body for POST /bypass."""

    status: str  # "success" or "error"
    cookies: Dict[str, str] = Field(default_factory=dict)
    html: Optional[str] = None
    duration: float = 0.0
    error: Optional[str] = None


class StatusResponse(BaseModel):
    """Response body for GET /cookies."""

    domains: List[CookieInfo]
    total: int


class DeleteResponse(BaseModel):
    """Response body for DELETE /cookies/{domain}."""

    status: str
    domain: str

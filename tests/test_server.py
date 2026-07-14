"""Tests for the FastAPI server endpoints."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from cf_bypass.strategies.base import BypassResult


@pytest.fixture
def mock_orchestrator():
    """Return a mock orchestrator for server tests."""
    orch = AsyncMock()
    orch.bypass.return_value = BypassResult(
        success=True,
        html="<html>Content</html>",
        cookies={"cf_clearance": "test"},
        strategy_name="playwright",
        level=3,
        duration=2.5,
        status_code=200,
    )
    return orch


@pytest.fixture
def mock_cookie_manager():
    """Return a mock cookie manager for server tests."""
    cm = AsyncMock()
    cm.list_all.return_value = [
        {
            "domain": "example.com",
            "cookie_count": 2,
            "created_at": "2026-07-14T10:00:00+00:00",
            "expires_at": "2026-07-15T10:00:00+00:00",
            "last_used": "2026-07-14T10:30:00+00:00",
            "has_cf_clearance": True,
        },
    ]
    cm.clear_domain.return_value = True
    return cm


@pytest.fixture
def client(mock_orchestrator, mock_cookie_manager):
    """Create a TestClient with mocked dependencies."""
    from cf_bypass.server.app import app, _state

    _state.orchestrator = mock_orchestrator
    _state.cookie_manager = mock_cookie_manager

    with TestClient(app) as tc:
        yield tc


class TestHealthEndpoint:
    def test_health_returns_ok(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"
        assert response.json()["service"] == "cf-bypass-cli"


class TestBypassEndpoint:
    def test_successful_bypass(self, client, mock_orchestrator):
        response = client.post("/bypass", json={
            "url": "https://example.com",
            "timeout": 60,
        })

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["cookies"]["cf_clearance"] == "test"
        assert data["html"] is not None

    def test_cookie_only(self, client, mock_orchestrator):
        mock_orchestrator.bypass.return_value = BypassResult(
            success=True,
            html="<html>Content</html>",
            cookies={"cf_clearance": "test"},
            strategy_name="playwright",
            level=3,
            duration=2.5,
            status_code=200,
        )

        response = client.post("/bypass", json={
            "url": "https://example.com",
            "cookie_only": True,
        })

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["html"] is None
        assert data["cookies"]["cf_clearance"] == "test"

    def test_failed_bypass(self, client, mock_orchestrator):
        mock_orchestrator.bypass.return_value = BypassResult(
            success=False,
            error="All strategies failed",
            strategy_name="all_failed",
        )

        response = client.post("/bypass", json={
            "url": "https://blocked.com",
        })

        assert response.status_code == 200  # HTTP 200, but status field is "error"
        data = response.json()
        assert data["status"] == "error"
        assert data["error"] is not None

    def test_invalid_request(self, client):
        """Missing required 'url' field."""
        response = client.post("/bypass", json={})
        assert response.status_code == 422  # Validation error


class TestCookiesEndpoint:
    def test_list_cookies(self, client):
        response = client.get("/cookies")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["domains"][0]["domain"] == "example.com"

    def test_delete_cookies(self, client):
        response = client.delete("/cookies/example.com")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "deleted"

    def test_delete_nonexistent(self, client, mock_cookie_manager):
        mock_cookie_manager.clear_domain.return_value = False
        response = client.delete("/cookies/nope.com")
        assert response.status_code == 404

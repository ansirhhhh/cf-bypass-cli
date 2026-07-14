"""Tests for CookieManager — persistence, expiry, validation."""

import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from cf_bypass.cookie_manager import CookieManager


@pytest.fixture
def tmp_storage():
    """Create a temporary storage directory for cookie files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def cookie_manager(tmp_storage):
    """CookieManager bound to a temp directory."""
    return CookieManager(str(tmp_storage))


class TestStoreAndRetrieve:
    @pytest.mark.asyncio
    async def test_store_then_retrieve(self, cookie_manager):
        domain = "example.com"
        cookies = {"cf_clearance": "abc", "__cf_bm": "xyz"}

        await cookie_manager.store(domain, cookies)
        retrieved = await cookie_manager.get_valid_cookies(domain)

        assert retrieved is not None
        assert retrieved["cf_clearance"] == "abc"
        assert retrieved["__cf_bm"] == "xyz"

    @pytest.mark.asyncio
    async def test_no_file_returns_none(self, cookie_manager):
        result = await cookie_manager.get_valid_cookies("nonexistent.com")
        assert result is None

    @pytest.mark.asyncio
    async def test_file_structure(self, cookie_manager, tmp_storage):
        domain = "example.com"
        cookies = {"cf_clearance": "tok"}

        await cookie_manager.store(domain, cookies)

        # Check the JSON file exists and has correct structure
        safe_name = domain.replace(".", "_")
        file_path = Path(tmp_storage) / f"{safe_name}.json"

        assert file_path.exists()
        data = json.loads(file_path.read_text())
        assert data["domain"] == domain
        assert data["cookies"] == cookies
        assert "created_at" in data
        assert "expires_at" in data
        assert "last_used" in data


class TestExpiry:
    @pytest.mark.asyncio
    async def test_expired_returns_none(self, cookie_manager, tmp_storage):
        """Write a cookie file with past expiry; get_valid_cookies should return None."""
        domain = "expired.com"
        safe_name = domain.replace(".", "_")
        file_path = Path(tmp_storage) / f"{safe_name}.json"

        past = datetime.now(timezone.utc) - timedelta(hours=10)
        data = {
            "domain": domain,
            "cookies": {"cf_clearance": "old"},
            "created_at": (past - timedelta(hours=24)).isoformat(),
            "expires_at": past.isoformat(),
            "user_agent": "",
            "last_used": past.isoformat(),
        }
        file_path.write_text(json.dumps(data))

        result = await cookie_manager.get_valid_cookies(domain)
        assert result is None

    @pytest.mark.asyncio
    async def test_future_expiry_returns_cookies(self, cookie_manager, tmp_storage):
        """Write a cookie file with future expiry; should be retrieved."""
        domain = "fresh.com"
        safe_name = domain.replace(".", "_")
        file_path = Path(tmp_storage) / f"{safe_name}.json"

        future = datetime.now(timezone.utc) + timedelta(hours=10)
        data = {
            "domain": domain,
            "cookies": {"cf_clearance": "fresh_token"},
            "created_at": datetime.now(timezone.utc).isoformat(),
            "expires_at": future.isoformat(),
            "user_agent": "",
            "last_used": datetime.now(timezone.utc).isoformat(),
        }
        file_path.write_text(json.dumps(data))

        result = await cookie_manager.get_valid_cookies(domain)
        assert result is not None
        assert result["cf_clearance"] == "fresh_token"


class TestClear:
    @pytest.mark.asyncio
    async def test_clear_all(self, cookie_manager):
        await cookie_manager.store("a.com", {"cf_clearance": "1"})
        await cookie_manager.store("b.com", {"cf_clearance": "2"})

        count = await cookie_manager.clear_all()
        assert count == 2

        # Both should be gone
        assert await cookie_manager.get_valid_cookies("a.com") is None
        assert await cookie_manager.get_valid_cookies("b.com") is None

    @pytest.mark.asyncio
    async def test_clear_specific_domain(self, cookie_manager):
        await cookie_manager.store("keep.com", {"cf_clearance": "keep"})
        await cookie_manager.store("remove.com", {"cf_clearance": "remove"})

        deleted = await cookie_manager.clear_domain("remove.com")
        assert deleted is True

        assert await cookie_manager.get_valid_cookies("keep.com") is not None
        assert await cookie_manager.get_valid_cookies("remove.com") is None

    @pytest.mark.asyncio
    async def test_clear_nonexistent(self, cookie_manager):
        deleted = await cookie_manager.clear_domain("nope.com")
        assert deleted is False


class TestListAll:
    @pytest.mark.asyncio
    async def test_list_empty(self, cookie_manager):
        result = await cookie_manager.list_all()
        assert result == []

    @pytest.mark.asyncio
    async def test_list_with_cookies(self, cookie_manager):
        await cookie_manager.store("a.com", {"cf_clearance": "1"})
        await cookie_manager.store("b.com", {"cf_clearance": "2"})

        result = await cookie_manager.list_all()
        assert len(result) == 2
        assert {r["domain"] for r in result} == {"a.com", "b.com"}

        # Check fields
        for r in result:
            assert "domain" in r
            assert "cookie_count" in r
            assert "has_cf_clearance" in r
            assert r["has_cf_clearance"] is True


class TestUpdateLastUsed:
    @pytest.mark.asyncio
    async def test_bumps_timestamp(self, cookie_manager):
        domain = "test.com"
        await cookie_manager.store(domain, {"cf_clearance": "tok"})

        # Get initial last_used
        cookies = await cookie_manager.get_valid_cookies(domain)
        assert cookies is not None

        # Read the file to get initial timestamp
        safe_name = domain.replace(".", "_")
        file_path = cookie_manager._domain_to_path(domain)
        data_before = json.loads(file_path.read_text())
        before = data_before["last_used"]

        # Wait a moment then update
        import asyncio
        await asyncio.sleep(0.1)
        await cookie_manager.update_last_used(domain)

        data_after = json.loads(file_path.read_text())
        after = data_after["last_used"]
        assert after != before

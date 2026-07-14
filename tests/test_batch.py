"""Tests for batch URL processor."""

import tempfile
import csv
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from cf_bypass.batch.processor import BatchProcessor
from cf_bypass.strategies.base import BypassResult


@pytest.fixture
def mock_orchestrator():
    orch = AsyncMock()
    orch.bypass.return_value = BypassResult(
        success=True,
        html="<html>Content</html>",
        cookies={"cf_clearance": "test_token"},
        strategy_name="curl_cffi",
        level=2,
        duration=1.5,
        status_code=200,
    )
    return orch


@pytest.fixture
def processor(mock_orchestrator):
    return BatchProcessor(mock_orchestrator)


class TestReadUrls:
    def test_reads_urls(self):
        """_read_urls filters out comments and blank lines."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        ) as f:
            f.write("https://example.com\n")
            f.write("# this is a comment\n")
            f.write("\n")
            f.write("https://test.com\n")
            tmp = f.name

        try:
            proc = BatchProcessor(AsyncMock())
            urls = proc._read_urls(tmp)
            assert urls == ["https://example.com", "https://test.com"]
        finally:
            Path(tmp).unlink()

    def test_empty_file(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        ) as f:
            f.write("# only comments\n")
            tmp = f.name

        try:
            proc = BatchProcessor(AsyncMock())
            urls = proc._read_urls(tmp)
            assert urls == []
        finally:
            Path(tmp).unlink()


class TestProcessUrls:
    @pytest.mark.asyncio
    async def test_process_urls_writes_csv(self, processor, tmp_path):
        output = tmp_path / "results.csv"

        results = await processor.process_urls(
            urls=["https://a.com", "https://b.com"],
            output_path=str(output),
        )

        assert len(results) == 2
        assert results[0]["success"] is True
        assert results[0]["strategy"] == "curl_cffi"

        # Verify CSV was written
        assert output.exists()
        with output.open(encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            assert len(rows) == 2
            assert rows[0]["url"] == "https://a.com"
            assert rows[0]["success"] == "True"

    @pytest.mark.asyncio
    async def test_process_file(self, processor, tmp_path):
        """Integration: read URLs from file, write CSV."""
        input_file = tmp_path / "urls.txt"
        input_file.write_text("https://x.com\nhttps://y.com\n", encoding="utf-8")

        output = tmp_path / "out.csv"

        results = await processor.process_file(
            input_path=str(input_file),
            output_path=str(output),
        )

        assert len(results) == 2
        assert output.exists()

    @pytest.mark.asyncio
    async def test_results_include_error_field(self, processor, tmp_path):
        output = tmp_path / "errors.csv"

        results = await processor.process_urls(
            urls=["https://fail.com"],
            output_path=str(output),
        )

        assert "error" in results[0]
        assert "has_cf_clearance" in results[0]

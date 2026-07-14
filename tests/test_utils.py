"""Tests for utility functions."""

import pytest
from cf_bypass.utils import extract_domain, normalize_url, is_valid_url, sanitize_filename


class TestExtractDomain:
    def test_with_scheme(self):
        assert extract_domain("https://example.com/path") == "example.com"

    def test_without_scheme(self):
        assert extract_domain("example.com/path") == "example.com"

    def test_with_port(self):
        assert extract_domain("https://example.com:8080/path") == "example.com"

    def test_subdomain(self):
        assert extract_domain("https://sub.example.co.uk/path?q=1") == "sub.example.co.uk"

    def test_ip_address(self):
        assert extract_domain("https://192.168.1.1:8080/admin") == "192.168.1.1"


class TestNormalizeUrl:
    def test_adds_scheme(self):
        assert normalize_url("example.com") == "https://example.com"

    def test_preserves_scheme(self):
        assert normalize_url("http://example.com") == "http://example.com"
        assert normalize_url("https://example.com") == "https://example.com"

    def test_strips_whitespace(self):
        assert normalize_url("  example.com  ") == "https://example.com"


class TestIsValidUrl:
    def test_valid_url(self):
        assert is_valid_url("https://example.com") is True
        assert is_valid_url("example.com") is True
        assert is_valid_url("https://sub.example.com/path?a=1") is True

    def test_invalid_url(self):
        assert is_valid_url("") is False
        assert is_valid_url("not-a-url") is False
        assert is_valid_url("ftp://example.com") is False


class TestSanitizeFilename:
    def test_domain(self):
        assert sanitize_filename("example.com") == "example.com"

    def test_special_chars(self):
        assert sanitize_filename("test:8080") == "test_8080"

    def test_windows_path_chars(self):
        result = sanitize_filename("a<b>c:d?e*f")
        assert "<" not in result
        assert ">" not in result
        assert ":" not in result
        assert "?" not in result
        assert "*" not in result

"""Tests for configuration management."""

import os
import tempfile
from pathlib import Path

import pytest
import yaml

from cf_bypass.config import Config, ProxyConfig, StorageConfig


class TestConfigDefaults:
    """Default config when no file exists."""

    def test_default_timeout(self):
        config = Config()
        assert config.timeout == 60

    def test_default_headless(self):
        config = Config()
        assert config.headless is False

    def test_default_strategies(self):
        config = Config()
        assert "cloudscraper" in config.enabled_strategies
        assert "curl_cffi" in config.enabled_strategies
        assert "playwright" in config.enabled_strategies
        assert "nodriver" in config.enabled_strategies

    def test_default_proxy_disabled(self):
        config = Config()
        assert config.proxy.enabled is False
        assert config.proxy.get_url() is None

    def test_storage_path_expanded(self):
        config = Config()
        assert config.storage_path == os.path.expanduser("~/.cf-bypass/cookies")


class TestConfigFromDict:
    """Building config from parsed YAML."""

    def test_custom_values(self):
        cfg = Config._from_dict({
            "timeout": 30,
            "headless": True,
            "strategies": ["playwright", "nodriver"],
        })
        assert cfg.timeout == 30
        assert cfg.headless is True
        assert cfg.enabled_strategies == ["playwright", "nodriver"]

    def test_partial_override(self):
        cfg = Config._from_dict({"timeout": 90})
        assert cfg.timeout == 90
        assert len(cfg.enabled_strategies) == 4  # defaults preserved

    def test_proxy_config(self):
        cfg = Config._from_dict({
            "proxy": {
                "enabled": True,
                "url": "http://proxy:8080",
            }
        })
        assert cfg.proxy.enabled is True
        assert cfg.proxy.get_url() == "http://proxy:8080"

    def test_proxy_config_new_fields(self):
        """Verify new proxy fields have correct defaults."""
        cfg = Config._from_dict({
            "proxy": {
                "enabled": True,
                "url": "http://proxy:8080",
                "type": "residential",
                "geo_required": "AU",
                "health_check": True,
            }
        })
        assert cfg.proxy.type == "residential"
        assert cfg.proxy.geo_required == "AU"
        assert cfg.proxy.health_check is True

    def test_proxy_config_defaults_new_fields(self):
        """Old config without new fields keeps sensible defaults."""
        cfg = Config._from_dict({
            "proxy": {
                "enabled": True,
                "url": "http://proxy:8080",
            }
        })
        assert cfg.proxy.type == "datacenter"
        assert cfg.proxy.geo_required == ""
        assert cfg.proxy.health_check is False


class TestConfigLoadFromFile:
    """Loading config from a real YAML file."""

    def test_load_valid_yaml(self):
        data = {
            "timeout": 42,
            "headless": True,
            "strategies": ["cloudscraper"],
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            yaml.dump(data, f)
            tmp = f.name

        try:
            cfg = Config.load(tmp)
            assert cfg.timeout == 42
            assert cfg.headless is True
        finally:
            os.unlink(tmp)

    def test_load_nonexistent_file(self):
        cfg = Config.load("/nonexistent/path/config.yaml")
        assert cfg.timeout == 60  # defaults

    def test_load_empty_file_uses_defaults(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write("")
            tmp = f.name

        try:
            cfg = Config.load(tmp)
            assert cfg.timeout == 60
        finally:
            os.unlink(tmp)


class TestProxyConfig:
    """ProxyConfig helper tests."""

    def test_get_url_disabled(self):
        p = ProxyConfig(enabled=False, url="http://proxy:8080")
        assert p.get_url() is None

    def test_get_url_enabled(self):
        p = ProxyConfig(enabled=True, url="http://proxy:8080")
        assert p.get_url() == "http://proxy:8080"

    def test_get_url_empty(self):
        p = ProxyConfig(enabled=True, url="")
        assert p.get_url() is None


class TestConfigInitConfig:
    """init_config creates directory and default file."""

    def test_creates_config_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / ".cf-bypass"
            config_path = config_dir / "config.yaml"

            # Monkey-patch default path
            old_default = Config._default_config_path
            Config._default_config_path = staticmethod(lambda: str(config_path))

            try:
                result = Config.init_config()
                assert config_path.exists()
                assert result == str(config_path)
            finally:
                Config._default_config_path = old_default

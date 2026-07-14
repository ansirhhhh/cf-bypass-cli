"""Configuration management for cf-bypass-cli.

Loads settings from ~/.cf-bypass/config.yaml with sensible defaults.
"""

import os
from pathlib import Path
from typing import Optional, List

import yaml

from cf_bypass.exceptions import ConfigError
from cf_bypass.logging_config import get_logger

logger = get_logger("config")

DEFAULT_CONFIG_YAML = """\
# cf-bypass-cli configuration
timeout: 60
headless: false

strategies:
  - cloudscraper
  - curl_cffi
  - playwright
  - nodriver

proxy:
  enabled: false
  url: ""

storage:
  path: "~/.cf-bypass/cookies"
  encryption: false
"""


class ProxyConfig:
    """Proxy configuration."""

    def __init__(self, enabled: bool = False, url: str = ""):
        self.enabled: bool = enabled
        self.url: str = url

    def get_url(self) -> Optional[str]:
        """Return proxy URL if enabled and non-empty, else None."""
        if self.enabled and self.url:
            return self.url
        return None

    def __repr__(self) -> str:
        return f"ProxyConfig(enabled={self.enabled}, url={self.url!r})"


class StorageConfig:
    """Storage configuration."""

    def __init__(self, path: str = "~/.cf-bypass/cookies", encryption: bool = False):
        self.path: str = os.path.expanduser(path)
        self.encryption: bool = encryption

    def __repr__(self) -> str:
        return f"StorageConfig(path={self.path!r}, encryption={self.encryption})"


class Config:
    """Main configuration object."""

    def __init__(
        self,
        timeout: int = 60,
        headless: bool = False,
        enabled_strategies: Optional[List[str]] = None,
        proxy: Optional[ProxyConfig] = None,
        storage: Optional[StorageConfig] = None,
    ):
        self.timeout: int = timeout
        self.headless: bool = headless
        self.enabled_strategies: List[str] = enabled_strategies or [
            "cloudscraper",
            "curl_cffi",
            "playwright",
            "nodriver",
        ]
        self.proxy: ProxyConfig = proxy or ProxyConfig()
        self.storage: StorageConfig = storage or StorageConfig()

    @property
    def storage_path(self) -> str:
        return self.storage.path

    @classmethod
    def load(cls, config_path: Optional[str] = None) -> "Config":
        """Load configuration from YAML file, falling back to defaults.

        Args:
            config_path: Explicit path to config file. If None, checks
                         ~/.cf-bypass/config.yaml and XDG_CONFIG_HOME.

        Returns:
            Config object populated from file or defaults.
        """
        if config_path is None:
            config_path = cls._default_config_path()

        config_file = Path(config_path)

        if not config_file.exists():
            logger.info(f"No config file found at {config_path}, using defaults")
            return cls()

        try:
            data = yaml.safe_load(config_file.read_text(encoding="utf-8"))
            if data is None:
                logger.warning(f"Empty config file at {config_path}, using defaults")
                return cls()

            return cls._from_dict(data)

        except yaml.YAMLError as e:
            logger.warning(f"Failed to parse config file: {e}, using defaults")
            return cls()
        except Exception as e:
            logger.error(f"Unexpected error loading config: {e}")
            return cls()

    @classmethod
    def _from_dict(cls, data: dict) -> "Config":
        """Build Config from parsed YAML dictionary."""
        timeout = data.get("timeout", 60)
        headless = data.get("headless", False)
        enabled_strategies = data.get("strategies", [
            "cloudscraper", "curl_cffi", "playwright", "nodriver",
        ])

        proxy_data = data.get("proxy", {})
        proxy = ProxyConfig(
            enabled=proxy_data.get("enabled", False),
            url=proxy_data.get("url", ""),
        )

        storage_data = data.get("storage", {})
        storage = StorageConfig(
            path=storage_data.get("path", "~/.cf-bypass/cookies"),
            encryption=storage_data.get("encryption", False),
        )

        return cls(
            timeout=timeout,
            headless=headless,
            enabled_strategies=enabled_strategies,
            proxy=proxy,
            storage=storage,
        )

    @staticmethod
    def _default_config_path() -> str:
        """Determine the default config file path."""
        xdg_config = os.environ.get("XDG_CONFIG_HOME", "")
        if xdg_config:
            return os.path.join(xdg_config, "cf-bypass", "config.yaml")
        return os.path.expanduser("~/.cf-bypass/config.yaml")

    @classmethod
    def init_config(cls) -> str:
        """Create default config directory and file. Returns the config path."""
        config_path = cls._default_config_path()
        config_dir = os.path.dirname(config_path)
        os.makedirs(config_dir, exist_ok=True)

        config_file = Path(config_path)
        if not config_file.exists():
            config_file.write_text(DEFAULT_CONFIG_YAML, encoding="utf-8")
            logger.info(f"Created default config at {config_path}")
        else:
            logger.info(f"Config file already exists at {config_path}")

        return config_path

    def __repr__(self) -> str:
        return (
            f"Config(timeout={self.timeout}, headless={self.headless}, "
            f"strategies={self.enabled_strategies}, "
            f"proxy={self.proxy!r}, storage={self.storage!r})"
        )

"""Configuration management for cf-bypass-cli v2.0.

Loads settings from ~/.cf-bypass/config.yaml with sensible defaults.
v2.0 adds: captcha, humanize, fingerprint, proxy pool, routing, observability.
"""

import os
from pathlib import Path
from typing import Optional, List, Dict, Any

import yaml

from cf_bypass.exceptions import ConfigError
from cf_bypass.logging_config import get_logger

logger = get_logger("config")

DEFAULT_CONFIG_YAML = """\
# cf-bypass-cli configuration (v2.0)
timeout: 60
headless: false

# Strategy chain (L1-L6, in order)
strategies:
  - cloudscraper
  - curl_cffi
  - playwright
  - nodriver

# ------------------------------------------------------------------
# Proxy (single URL — backward compatible)
# ------------------------------------------------------------------
proxy:
  enabled: false
  url: ""
  type: "datacenter"
  geo_required: ""
  health_check: false

# ------------------------------------------------------------------
# Proxy pool (v2.0 — replaces single proxy when configured)
# ------------------------------------------------------------------
proxy_pool:
  enabled: false
  strategy: weighted          # round_robin | random | weighted | least_used
  cooldown_after_failures: 3
  cooldown_duration: 600
  health_check_interval: 300
  min_quality: 0.3
  nodes: []
  # - url: http://user:pass@proxy1:8080
  #   provider: manual
  #   geo: US
  #   type: residential

# ------------------------------------------------------------------
# Humanize behavior layer (L5)
# ------------------------------------------------------------------
humanize:
  enabled: true
  mouse_profile: windows_chrome
  typing_profile: casual
  warm_up:
    enabled: false
    sites:
      - https://news.ycombinator.com
      - https://www.bbc.com/news
    min_duration: 5
    max_duration: 15

# ------------------------------------------------------------------
# Fingerprint layer (L6)
# ------------------------------------------------------------------
fingerprint:
  enabled: true
  rotation: per_session         # per_session | per_request | sticky
  os_distribution:
    windows: 0.6
    macos: 0.3
    linux: 0.1
  canvas_noise: true
  canvas_noise_mode: subtle     # subtle | moderate | aggressive
  audio_noise: true
  fonts_spoof: true

# ------------------------------------------------------------------
# CAPTCHA solvers
# ------------------------------------------------------------------
captcha:
  timeout: 120
  max_retries: 2
  providers:
    turnstile:
      - capsolver
      - 2captcha
      - injection
    recaptcha_v2:
      - capsolver
      - 2captcha
    recaptcha_v3:
      - capsolver
    hcaptcha:
      - capsolver
      - 2captcha
    image:
      - 2captcha
      - llm_vision
  api_keys:
    capsolver: ""
    twocaptcha: ""
    openai: ""

# ------------------------------------------------------------------
# Smart routing (v2.0)
# ------------------------------------------------------------------
routing:
  smart: false                  # Enable quick_probe before strategy chain
  retry_policy:
    max_retries: 3
    base_delay: 1.0
    max_delay: 30.0
    jitter: 0.2

# ------------------------------------------------------------------
# Observability (v2.0)
# ------------------------------------------------------------------
observability:
  enabled: false
  storage: sqlite               # sqlite | none
  path: "~/.cf-bypass/metrics.db"
  dashboard_port: 0             # 0 = disabled

# ------------------------------------------------------------------
# Storage
# ------------------------------------------------------------------
storage:
  path: "~/.cf-bypass/cookies"
  encryption: false
"""


class ProxyConfig:
    """Proxy configuration with quality grading and health checks."""

    def __init__(
        self,
        enabled: bool = False,
        url: str = "",
        proxy_type: str = "datacenter",
        geo_required: str = "",
        health_check: bool = False,
    ):
        self.enabled: bool = enabled
        self.url: str = url
        self.type: str = proxy_type
        self.geo_required: str = geo_required
        self.health_check: bool = health_check

    def get_url(self) -> Optional[str]:
        """Return proxy URL if enabled and non-empty, else None."""
        if self.enabled and self.url:
            return self.url
        return None

    def __repr__(self) -> str:
        return (
            f"ProxyConfig(enabled={self.enabled}, url={self.url!r}, "
            f"type={self.type!r}, geo={self.geo_required!r}, "
            f"health_check={self.health_check})"
        )


class StorageConfig:
    """Storage configuration."""

    def __init__(self, path: str = "~/.cf-bypass/cookies", encryption: bool = False):
        self.path: str = os.path.expanduser(path)
        self.encryption: bool = encryption

    def __repr__(self) -> str:
        return f"StorageConfig(path={self.path!r}, encryption={self.encryption})"


class CaptchaConfig:
    """CAPTCHA solver configuration."""

    def __init__(
        self,
        timeout: int = 120,
        max_retries: int = 2,
        providers: Optional[Dict[str, List[str]]] = None,
        api_keys: Optional[Dict[str, str]] = None,
    ):
        self.timeout = timeout
        self.max_retries = max_retries
        self.providers = providers or {
            "turnstile": ["capsolver", "2captcha", "injection"],
            "recaptcha_v2": ["capsolver", "2captcha"],
            "recaptcha_v3": ["capsolver"],
            "hcaptcha": ["capsolver", "2captcha"],
            "image": ["2captcha", "llm_vision"],
        }
        self.api_keys = api_keys or {}

    def __repr__(self) -> str:
        return f"CaptchaConfig(timeout={self.timeout}, providers={list(self.providers.keys())})"


class HumanizeConfig:
    """Human behavior simulation config."""

    def __init__(
        self,
        enabled: bool = True,
        mouse_profile: str = "windows_chrome",
        typing_profile: str = "casual",
        warm_up_enabled: bool = False,
        warm_up_sites: Optional[List[str]] = None,
        warm_up_min: float = 5.0,
        warm_up_max: float = 15.0,
    ):
        self.enabled = enabled
        self.mouse_profile = mouse_profile
        self.typing_profile = typing_profile
        self.warm_up_enabled = warm_up_enabled
        self.warm_up_sites = warm_up_sites or [
            "https://news.ycombinator.com",
            "https://www.bbc.com/news",
        ]
        self.warm_up_min = warm_up_min
        self.warm_up_max = warm_up_max


class FingerprintConfig:
    """Fingerprint layer config."""

    def __init__(
        self,
        enabled: bool = True,
        rotation: str = "per_session",
        os_distribution: Optional[Dict[str, float]] = None,
        canvas_noise: bool = True,
        canvas_noise_mode: str = "subtle",
        audio_noise: bool = True,
        fonts_spoof: bool = True,
    ):
        self.enabled = enabled
        self.rotation = rotation
        self.os_distribution = os_distribution or {"windows": 0.6, "macos": 0.3, "linux": 0.1}
        self.canvas_noise = canvas_noise
        self.canvas_noise_mode = canvas_noise_mode
        self.audio_noise = audio_noise
        self.fonts_spoof = fonts_spoof


class RoutingConfig:
    """Smart routing and retry config."""

    def __init__(
        self,
        smart: bool = False,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
        jitter: float = 0.2,
    ):
        self.smart = smart
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.jitter = jitter


class ObservabilityConfig:
    """Metrics and dashboard config."""

    def __init__(
        self,
        enabled: bool = False,
        storage: str = "sqlite",
        path: str = "~/.cf-bypass/metrics.db",
        dashboard_port: int = 0,
    ):
        self.enabled = enabled
        self.storage = storage
        self.path = os.path.expanduser(path)
        self.dashboard_port = dashboard_port


class ProxyPoolConfig:
    """Multi-proxy pool configuration."""

    def __init__(
        self,
        enabled: bool = False,
        strategy: str = "weighted",
        cooldown_after_failures: int = 3,
        cooldown_duration: int = 600,
        health_check_interval: int = 300,
        min_quality: float = 0.3,
        nodes: Optional[List[Dict[str, Any]]] = None,
    ):
        self.enabled = enabled
        self.strategy = strategy
        self.cooldown_after_failures = cooldown_after_failures
        self.cooldown_duration = cooldown_duration
        self.health_check_interval = health_check_interval
        self.min_quality = min_quality
        self.nodes = nodes or []


class Config:
    """Main configuration object (v2.0)."""

    def __init__(
        self,
        timeout: int = 60,
        headless: bool = False,
        enabled_strategies: Optional[List[str]] = None,
        proxy: Optional[ProxyConfig] = None,
        storage: Optional[StorageConfig] = None,
        captcha: Optional[CaptchaConfig] = None,
        humanize: Optional[HumanizeConfig] = None,
        fingerprint: Optional[FingerprintConfig] = None,
        proxy_pool: Optional[ProxyPoolConfig] = None,
        routing: Optional[RoutingConfig] = None,
        observability: Optional[ObservabilityConfig] = None,
    ):
        self.timeout: int = timeout
        self.headless: bool = headless
        self.enabled_strategies: List[str] = enabled_strategies or [
            "cloudscraper", "curl_cffi", "playwright", "nodriver",
        ]
        self.proxy: ProxyConfig = proxy or ProxyConfig()
        self.storage: StorageConfig = storage or StorageConfig()
        self.captcha: CaptchaConfig = captcha or CaptchaConfig()
        self.humanize: HumanizeConfig = humanize or HumanizeConfig()
        self.fingerprint: FingerprintConfig = fingerprint or FingerprintConfig()
        self.proxy_pool: ProxyPoolConfig = proxy_pool or ProxyPoolConfig()
        self.routing: RoutingConfig = routing or RoutingConfig()
        self.observability: ObservabilityConfig = observability or ObservabilityConfig()

    @property
    def storage_path(self) -> str:
        return self.storage.path

    @classmethod
    def load(cls, config_path: Optional[str] = None) -> "Config":
        """Load configuration from YAML file, falling back to defaults."""
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

        # Proxy (single)
        proxy_data = data.get("proxy", {})
        proxy = ProxyConfig(
            enabled=proxy_data.get("enabled", False),
            url=proxy_data.get("url", ""),
            proxy_type=proxy_data.get("type", "datacenter"),
            geo_required=proxy_data.get("geo_required", ""),
            health_check=proxy_data.get("health_check", False),
        )

        # Storage
        storage_data = data.get("storage", {})
        storage = StorageConfig(
            path=storage_data.get("path", "~/.cf-bypass/cookies"),
            encryption=storage_data.get("encryption", False),
        )

        # Captcha
        captcha_data = data.get("captcha", {})
        captcha = CaptchaConfig(
            timeout=captcha_data.get("timeout", 120),
            max_retries=captcha_data.get("max_retries", 2),
            providers=captcha_data.get("providers"),
            api_keys=captcha_data.get("api_keys", {}),
        )

        # Humanize
        hum_data = data.get("humanize", {})
        warm_up = hum_data.get("warm_up", {})
        humanize = HumanizeConfig(
            enabled=hum_data.get("enabled", True),
            mouse_profile=hum_data.get("mouse_profile", "windows_chrome"),
            typing_profile=hum_data.get("typing_profile", "casual"),
            warm_up_enabled=warm_up.get("enabled", False),
            warm_up_sites=warm_up.get("sites"),
            warm_up_min=warm_up.get("min_duration", 5),
            warm_up_max=warm_up.get("max_duration", 15),
        )

        # Fingerprint
        fp_data = data.get("fingerprint", {})
        fingerprint = FingerprintConfig(
            enabled=fp_data.get("enabled", True),
            rotation=fp_data.get("rotation", "per_session"),
            os_distribution=fp_data.get("os_distribution"),
            canvas_noise=fp_data.get("canvas_noise", True),
            canvas_noise_mode=fp_data.get("canvas_noise_mode", "subtle"),
            audio_noise=fp_data.get("audio_noise", True),
            fonts_spoof=fp_data.get("fonts_spoof", True),
        )

        # Proxy pool
        pp_data = data.get("proxy_pool", {})
        proxy_pool = ProxyPoolConfig(
            enabled=pp_data.get("enabled", False),
            strategy=pp_data.get("strategy", "weighted"),
            cooldown_after_failures=pp_data.get("cooldown_after_failures", 3),
            cooldown_duration=pp_data.get("cooldown_duration", 600),
            health_check_interval=pp_data.get("health_check_interval", 300),
            min_quality=pp_data.get("min_quality", 0.3),
            nodes=pp_data.get("nodes", []),
        )

        # Routing
        rt_data = data.get("routing", {})
        retry_data = rt_data.get("retry_policy", {})
        routing = RoutingConfig(
            smart=rt_data.get("smart", False),
            max_retries=retry_data.get("max_retries", 3),
            base_delay=retry_data.get("base_delay", 1.0),
            max_delay=retry_data.get("max_delay", 30.0),
            jitter=retry_data.get("jitter", 0.2),
        )

        # Observability
        obs_data = data.get("observability", {})
        observability = ObservabilityConfig(
            enabled=obs_data.get("enabled", False),
            storage=obs_data.get("storage", "sqlite"),
            path=obs_data.get("path", "~/.cf-bypass/metrics.db"),
            dashboard_port=obs_data.get("dashboard_port", 0),
        )

        return cls(
            timeout=timeout,
            headless=headless,
            enabled_strategies=enabled_strategies,
            proxy=proxy,
            storage=storage,
            captcha=captcha,
            humanize=humanize,
            fingerprint=fingerprint,
            proxy_pool=proxy_pool,
            routing=routing,
            observability=observability,
        )

    @staticmethod
    def _default_config_path() -> str:
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
            f"strategies={self.enabled_strategies})"
        )

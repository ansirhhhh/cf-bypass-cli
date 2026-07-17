"""Fingerprint profile data model.

A FingerprintProfile captures every detectable browser dimension that
anti-bot systems (FingerprintJS, DataDome, Cloudflare Bot Manager)
use to identify automation. All fields are internally consistent
(e.g., Apple M2 GPU only appears on macOS, viewport <= screen).
"""

from dataclasses import dataclass, field
from typing import List, Tuple, Literal, Optional


@dataclass
class FingerprintProfile:
    """A single, internally-consistent browser fingerprint.

    Generated once per session (or per request in 'per_request' mode)
    by FingerprintGenerator. Injected into L3/L4 browser contexts
    before navigation.

    All string fields match what real Chrome returns for the given
    OS/browser version combination.
    """

    # ==================================================================
    # OS / Browser identity
    # ==================================================================

    os: Literal["windows", "macos", "linux"] = "windows"
    os_version: str = "10.0.22631"  # Windows 11 23H2
    browser: Literal["chrome"] = "chrome"
    browser_version: str = "120.0.6099.130"
    ua_string: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )

    # ==================================================================
    # Screen / Viewport
    # ==================================================================

    screen_resolution: Tuple[int, int] = (2560, 1440)
    viewport: Tuple[int, int] = (1920, 1080)
    device_scale_factor: float = 1.0
    color_depth: int = 24
    pixel_ratio: float = 1.0

    # ==================================================================
    # Locale / Time (MUST match proxy geo when used)
    # ==================================================================

    locale: str = "en-US"
    languages: List[str] = field(default_factory=lambda: ["en-US", "en"])
    timezone: str = "America/New_York"
    timezone_offset: int = -300  # minutes from UTC

    # ==================================================================
    # Hardware specs
    # ==================================================================

    hardware_concurrency: int = 8
    device_memory: int = 8  # GB
    max_touch_points: int = 0  # 0 = desktop

    # ==================================================================
    # GPU / WebGL
    # ==================================================================

    webgl_vendor: str = "Intel Inc."
    webgl_renderer: str = "Intel Iris OpenGL Engine"
    gpu_vendor_id: str = "0x8086"  # Intel

    # ==================================================================
    # Canvas / Audio noise seeds (16-bit per session)
    # ==================================================================

    canvas_noise_seed: int = 0
    audio_noise_seed: int = 0

    # ==================================================================
    # Fonts (OS-appropriate set)
    # ==================================================================

    available_fonts: List[str] = field(default_factory=list)

    # ==================================================================
    # Network
    # ==================================================================

    connection_type: str = "4g"
    connection_rtt: int = 100  # ms
    connection_downlink: float = 10.0  # Mbps

    # ==================================================================
    # Session metadata (not injected, for tracking)
    # ==================================================================

    profile_id: str = ""
    generated_at: float = 0.0

    # ==================================================================
    # Derived convenience properties
    # ==================================================================

    @property
    def platform(self) -> str:
        """Return navigator.platform value matching the OS."""
        return {
            "windows": "Win32",
            "macos": "MacIntel",
            "linux": "Linux x86_64",
        }[self.os]

    @property
    def oscpu(self) -> str:
        """Return navigator.oscpu value."""
        if self.os == "windows":
            return "Windows NT 10.0; Win64; x64"
        elif self.os == "macos":
            return "Intel Mac OS X 10_15_7"
        return "Linux x86_64"

    @property
    def browser_major(self) -> int:
        """Return the Chrome major version number."""
        try:
            return int(self.browser_version.split(".")[0])
        except (ValueError, IndexError):
            return 120

    def to_dict(self) -> dict:
        """Return a JSON-serializable dict (for logging/debugging)."""
        return {
            "os": self.os,
            "browser_version": self.browser_version,
            "screen": f"{self.screen_resolution[0]}x{self.screen_resolution[1]}",
            "viewport": f"{self.viewport[0]}x{self.viewport[1]}",
            "locale": self.locale,
            "timezone": self.timezone,
            "cores": self.hardware_concurrency,
            "memory": f"{self.device_memory}GB",
            "gpu": self.webgl_renderer,
            "connection": self.connection_type,
            "profile_id": self.profile_id,
        }

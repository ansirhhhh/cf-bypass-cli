"""Fingerprint profile generator with real-world distribution sampling.

Generates internally-consistent FingerprintProfile instances by sampling
from distributions that match real-world device statistics. This avoids
the "every session looks identical" detection vector.

Distributions (sourced from statcounter + hardware surveys, 2026):
- OS: Windows 60%, macOS 30%, Linux 10%
- Screen: primarily 1920x1080 (35%), 2560x1440 (25%), 1366x768 (15%)
- Cores: 4 (30%), 8 (40%), 12 (15%), 16 (10%)
- Memory: 8GB (40%), 16GB (35%), 32GB (15%), 4GB (10%)
- Locale: en-US (50%), de-DE (10%), ja-JP (10%), zh-CN (8%), others (22%)
"""

import random
import time
import uuid
from typing import Optional, List, Tuple

from cf_bypass.fingerprint.profile import FingerprintProfile
from cf_bypass.fingerprint.consistency import ConsistencyValidator
from cf_bypass.logging_config import get_logger

logger = get_logger("fingerprint.generator")

# ======================================================================
# Real-world distributions
# ======================================================================

OS_DISTRIBUTION = {
    "windows": 0.60,
    "macos": 0.30,
    "linux": 0.10,
}

OS_VERSIONS = {
    "windows": ["10.0.22631", "10.0.19045", "10.0.22000"],
    "macos": ["14.5.0", "14.3.0", "13.6.0", "15.0.0"],
    "linux": ["6.5.0", "6.2.0", "5.15.0"],
}

CHROME_VERSIONS = [
    "120.0.6099.130",
    "120.0.6099.109",
    "119.0.6045.160",
    "119.0.6045.124",
    "118.0.5993.118",
]

SCREEN_RESOLUTIONS = {
    (1920, 1080): 0.35,
    (2560, 1440): 0.25,
    (1366, 768): 0.15,
    (1440, 900): 0.08,
    (3840, 2160): 0.05,
    (1680, 1050): 0.05,
    (1280, 720): 0.04,
    (1600, 900): 0.03,
}

HARDWARE_CONCURRENCY = {4: 0.30, 8: 0.40, 12: 0.15, 16: 0.10, 2: 0.05}
DEVICE_MEMORY = {8: 0.40, 16: 0.35, 32: 0.15, 4: 0.10}

LOCALE_DISTRIBUTION = {
    "en-US": 0.50,
    "de-DE": 0.10,
    "ja-JP": 0.10,
    "zh-CN": 0.08,
    "fr-FR": 0.05,
    "es-ES": 0.05,
    "pt-BR": 0.04,
    "ko-KR": 0.04,
    "it-IT": 0.02,
    "nl-NL": 0.02,
}

LOCALE_LANGUAGES = {
    "en-US": ["en-US", "en"],
    "de-DE": ["de-DE", "de", "en-US", "en"],
    "ja-JP": ["ja-JP", "ja", "en-US", "en"],
    "zh-CN": ["zh-CN", "zh", "en-US", "en"],
    "fr-FR": ["fr-FR", "fr", "en-US", "en"],
    "es-ES": ["es-ES", "es", "en-US", "en"],
    "pt-BR": ["pt-BR", "pt", "en-US", "en"],
    "ko-KR": ["ko-KR", "ko", "en-US", "en"],
    "it-IT": ["it-IT", "it", "en-US", "en"],
    "nl-NL": ["nl-NL", "nl", "en-US", "en"],
}

LOCALE_TIMEZONES = {
    "en-US": ["America/New_York", "America/Chicago", "America/Los_Angeles"],
    "de-DE": ["Europe/Berlin"],
    "ja-JP": ["Asia/Tokyo"],
    "zh-CN": ["Asia/Shanghai"],
    "fr-FR": ["Europe/Paris"],
    "es-ES": ["Europe/Madrid"],
    "pt-BR": ["America/Sao_Paulo"],
    "ko-KR": ["Asia/Seoul"],
    "it-IT": ["Europe/Rome"],
    "nl-NL": ["Europe/Amsterdam"],
}

GPU_BY_OS = {
    "windows": [
        ("Intel Inc.", "Intel Iris OpenGL Engine", "0x8086"),
        ("NVIDIA Corporation", "NVIDIA GeForce RTX 3060/PCIe/SSE2", "0x10DE"),
        ("AMD Inc.", "AMD Radeon Graphics", "0x1002"),
    ],
    "macos": [
        ("Apple Inc.", "Apple M2 Pro", "0x106B"),
        ("Apple Inc.", "Apple M1", "0x106B"),
    ],
    "linux": [
        ("Intel Inc.", "Mesa Intel UHD Graphics 620 (KBL GT2)", "0x8086"),
        ("AMD Inc.", "AMD Radeon Graphics (radeonsi, renoir, LLVM 15.0)", "0x1002"),
    ],
}

FONTS_BY_OS = {
    "windows": [
        "Arial", "Comic Sans MS", "Courier New", "Georgia",
        "Impact", "Times New Roman", "Trebuchet MS", "Verdana",
        "Segoe UI", "Calibri", "Cambria", "Candara", "Consolas",
        "Constantia", "Corbel", "Microsoft Sans Serif",
    ],
    "macos": [
        "Helvetica", "Times", "Courier", "Georgia",
        "Apple Color Emoji", "Geneva", "Monaco", "Lucida Grande",
        "SF Pro", "SF Mono", "SF Compact", "New York",
    ],
    "linux": [
        "DejaVu Sans", "DejaVu Serif", "DejaVu Sans Mono",
        "Liberation Sans", "Liberation Serif", "Liberation Mono",
        "FreeSans", "FreeSerif", "FreeMono",
        "Ubuntu", "Cantarell", "Noto Sans", "Noto Serif",
    ],
}

CONNECTION_PROFILES = {
    "4g": {"rtt": 100, "downlink": 10.0, "type": "4g"},
    "wifi": {"rtt": 50, "downlink": 25.0, "type": "wifi"},
    "ethernet": {"rtt": 25, "downlink": 50.0, "type": "ethernet"},
    "3g": {"rtt": 250, "downlink": 2.0, "type": "3g"},
}

CONNECTION_WEIGHTS = {"4g": 0.35, "wifi": 0.45, "ethernet": 0.15, "3g": 0.05}


# ======================================================================
# Generator
# ======================================================================


class FingerprintGenerator:
    """Generate realistic, internally-consistent fingerprint profiles.

    Usage::

        gen = FingerprintGenerator()
        fp = gen.generate()
        # Apply fp to browser:
        await apply_fingerprint(page, fp)
    """

    def __init__(self, seed: Optional[int] = None):
        """Initialize the generator.

        Args:
            seed: Optional random seed for reproducible profiles.
        """
        if seed is not None:
            random.seed(seed)
        self.validator = ConsistencyValidator()

    def generate(self, os_override: Optional[str] = None) -> FingerprintProfile:
        """Generate a random fingerprint profile.

        Args:
            os_override: Force a specific OS ("windows", "macos", "linux").
                         If None, samples from the real-world distribution.

        Returns:
            A complete, internally-consistent FingerprintProfile.
        """
        # 1. OS
        os_name = os_override or self._weighted_choice(OS_DISTRIBUTION)
        os_version = random.choice(OS_VERSIONS[os_name])

        # 2. Browser version (from last 3 stable releases)
        chrome_ver = random.choice(CHROME_VERSIONS)
        chrome_major = chrome_ver.split(".")[0]

        # 3. UA string
        ua = self._build_ua(os_name, chrome_ver)

        # 4. Screen / viewport
        screen_res = self._weighted_choice(SCREEN_RESOLUTIONS)
        # Viewport is screen minus ~80px for taskbar/chrome
        viewport = (screen_res[0], screen_res[1] - random.choice([40, 60, 80]))
        dsf = random.choices([1.0, 1.25, 1.5, 2.0], weights=[0.50, 0.15, 0.25, 0.10])[0]

        # 5. Locale / timezone / languages
        locale = self._weighted_choice(LOCALE_DISTRIBUTION)
        languages = LOCALE_LANGUAGES.get(locale, ["en-US", "en"])
        tz = random.choice(LOCALE_TIMEZONES.get(locale, ["America/New_York"]))
        tz_offset = self._timezone_offset(tz)

        # 6. Hardware
        cores = self._weighted_choice(HARDWARE_CONCURRENCY)
        memory = self._weighted_choice(DEVICE_MEMORY)
        touch_points = 0 if os_name != "linux" else random.choice([0, 0, 0, 5])

        # 7. GPU (OS-appropriate)
        gpu_vendor, gpu_renderer, gpu_id = random.choice(GPU_BY_OS[os_name])

        # 8. Noise seeds (16-bit random)
        canvas_seed = random.randint(0, 65535)
        audio_seed = random.randint(0, 65535)

        # 9. Fonts (OS-appropriate base set)
        fonts = list(FONTS_BY_OS[os_name])

        # 10. Network
        conn_type = self._weighted_choice(CONNECTION_WEIGHTS)
        conn_info = CONNECTION_PROFILES[conn_type]
        conn_rtt = conn_info["rtt"] + random.randint(-20, 20)
        conn_downlink = conn_info["downlink"] + random.uniform(-2, 5)

        profile = FingerprintProfile(
            os=os_name,
            os_version=os_version,
            browser="chrome",
            browser_version=chrome_ver,
            ua_string=ua,
            screen_resolution=screen_res,
            viewport=viewport,
            device_scale_factor=dsf,
            color_depth=24,
            pixel_ratio=dsf,
            locale=locale,
            languages=languages,
            timezone=tz,
            timezone_offset=tz_offset,
            hardware_concurrency=cores,
            device_memory=memory,
            max_touch_points=touch_points,
            webgl_vendor=gpu_vendor,
            webgl_renderer=gpu_renderer,
            gpu_vendor_id=gpu_id,
            canvas_noise_seed=canvas_seed,
            audio_noise_seed=audio_seed,
            available_fonts=fonts,
            connection_type=conn_type,
            connection_rtt=conn_rtt,
            connection_downlink=max(conn_downlink, 0.5),
            profile_id=str(uuid.uuid4())[:12],
            generated_at=time.time(),
        )

        # Validate consistency
        errors = self.validator.validate(profile)
        if errors:
            logger.warning(
                f"Generated profile has consistency issues: {errors}"
            )

        logger.debug(
            f"Generated fingerprint: os={os_name}, chrome={chrome_major}, "
            f"screen={screen_res[0]}x{screen_res[1]}, locale={locale}, "
            f"cores={cores}, mem={memory}GB, gpu={gpu_renderer[:30]}"
        )

        return profile

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _weighted_choice(dist: dict) -> any:
        """Pick a key from a distribution dict by weight."""
        items = list(dist.items())
        keys = [k for k, _ in items]
        weights = [w for _, w in items]
        return random.choices(keys, weights=weights, k=1)[0]

    @staticmethod
    def _build_ua(os_name: str, chrome_ver: str) -> str:
        """Build a Chrome User-Agent string matching the OS."""
        chrome_major = chrome_ver.split(".")[0]

        if os_name == "windows":
            return (
                f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                f"AppleWebKit/537.36 (KHTML, like Gecko) "
                f"Chrome/{chrome_major}.0.0.0 Safari/537.36"
            )
        elif os_name == "macos":
            return (
                f"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                f"AppleWebKit/537.36 (KHTML, like Gecko) "
                f"Chrome/{chrome_major}.0.0.0 Safari/537.36"
            )
        else:
            return (
                f"Mozilla/5.0 (X11; Linux x86_64) "
                f"AppleWebKit/537.36 (KHTML, like Gecko) "
                f"Chrome/{chrome_major}.0.0.0 Safari/537.36"
            )

    @staticmethod
    def _timezone_offset(tz_name: str) -> int:
        """Return UTC offset in minutes for a timezone name.

        This is a simplified mapping — production code should use
        zoneinfo or pytz for accurate DST-aware offsets.
        """
        offsets = {
            "America/New_York": -300,
            "America/Chicago": -360,
            "America/Los_Angeles": -480,
            "America/Sao_Paulo": -180,
            "Europe/Berlin": 60,
            "Europe/Paris": 60,
            "Europe/Madrid": 60,
            "Europe/Rome": 60,
            "Europe/Amsterdam": 60,
            "Asia/Tokyo": 540,
            "Asia/Shanghai": 480,
            "Asia/Seoul": 540,
        }
        return offsets.get(tz_name, 0)

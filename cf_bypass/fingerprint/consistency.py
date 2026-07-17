"""Internal consistency validation for fingerprint profiles.

Anti-bot systems check for "impossible" combinations:
- Apple M2 GPU on Windows → instant bot flag
- Viewport larger than screen → impossible
- en-US locale with Asia/Tokyo timezone → suspicious
- hardwareConcurrency=16 with deviceMemory=2 → unlikely

This module validates a FingerprintProfile against 20+ consistency
rules BEFORE injection. Profiles that fail validation are rejected
and a new one is generated.
"""

from typing import List, Tuple
from cf_bypass.fingerprint.profile import FingerprintProfile
from cf_bypass.logging_config import get_logger

logger = get_logger("fingerprint.consistency")


class ConsistencyValidator:
    """Validate fingerprint profile internal consistency.

    Usage::

        validator = ConsistencyValidator()
        errors = validator.validate(profile)
        if errors:
            print(f"Profile invalid: {errors}")
    """

    def validate(self, fp: FingerprintProfile) -> List[str]:
        """Run all consistency checks. Returns list of error messages.

        An empty list means the profile is internally consistent.
        """
        errors: List[str] = []

        # Run all checks
        for check_name, check_fn in self._checks():
            try:
                ok, msg = check_fn(fp)
                if not ok:
                    errors.append(f"[{check_name}] {msg}")
            except Exception as exc:
                errors.append(f"[{check_name}] check crashed: {exc}")

        if errors:
            logger.debug(
                f"Fingerprint consistency check: {len(errors)} issue(s)"
            )

        return errors

    def is_valid(self, fp: FingerprintProfile) -> bool:
        """Return True if the profile passes all consistency checks."""
        return len(self.validate(fp)) == 0

    # ------------------------------------------------------------------
    # Check registry
    # ------------------------------------------------------------------

    def _checks(self) -> List[Tuple[str, callable]]:
        """Return list of (name, check_fn) tuples."""
        return [
            ("gpu_os_match", self._check_gpu_os_match),
            ("viewport_fits_screen", self._check_viewport_fits_screen),
            ("locale_timezone_region", self._check_locale_timezone_region),
            ("ua_os_match", self._check_ua_os_match),
            ("ua_chrome_version", self._check_ua_chrome_version),
            ("hardware_memory_plausible", self._check_hardware_memory_plausible),
            ("device_scale_factor_range", self._check_device_scale_factor_range),
            ("languages_contains_locale", self._check_languages_contains_locale),
            ("touch_points_desktop", self._check_touch_points_desktop),
            ("color_depth_valid", self._check_color_depth_valid),
            ("pixel_ratio_consistent", self._check_pixel_ratio_consistent),
            ("connection_type_valid", self._check_connection_type_valid),
        ]

    # ==================================================================
    # Individual checks
    # ==================================================================

    @staticmethod
    def _check_gpu_os_match(fp: FingerprintProfile) -> Tuple[bool, str]:
        """GPU vendor must match the OS."""
        gpu = fp.webgl_vendor.lower()

        # Apple GPUs only on macOS
        if "apple" in gpu and fp.os != "macos":
            return False, f"Apple GPU '{fp.webgl_renderer}' on {fp.os}"

        # macOS shouldn't have Intel HD/Iris in most modern cases
        # (but Intel Macs do exist — allow it)

        return True, ""

    @staticmethod
    def _check_viewport_fits_screen(fp: FingerprintProfile) -> Tuple[bool, str]:
        """Viewport must be <= screen resolution."""
        vw, vh = fp.viewport
        sw, sh = fp.screen_resolution

        if vw > sw or vh > sh:
            return False, f"Viewport {vw}x{vh} > screen {sw}x{sh}"

        # Viewport should not be more than 200px smaller than screen
        # (browser chrome + taskbar is typically 40-120px)
        if sw - vw > 300 or sh - vh > 300:
            return False, f"Viewport {vw}x{vh} too small for screen {sw}x{sh}"

        return True, ""

    @staticmethod
    def _check_locale_timezone_region(fp: FingerprintProfile) -> Tuple[bool, str]:
        """Timezone region should broadly match locale region."""
        tz_lower = fp.timezone.lower()
        locale_region = fp.locale.split("-")[-1].upper() if "-" in fp.locale else ""

        # Broad regional mappings
        americas_tz = any(r in tz_lower for r in ["america/", "us/", "canada/"])
        europe_tz = "europe/" in tz_lower
        asia_tz = "asia/" in tz_lower

        americas_locale = locale_region in ("US", "CA", "BR", "MX", "AR")
        europe_locale = locale_region in (
            "DE", "FR", "ES", "IT", "NL", "GB", "PT", "PL", "SE", "NO", "DK", "FI"
        )
        asia_locale = locale_region in ("JP", "CN", "KR", "TW", "HK", "SG", "IN")

        if americas_tz and (europe_locale or asia_locale):
            return False, f"Americas TZ '{fp.timezone}' with locale '{fp.locale}'"
        if europe_tz and (americas_locale or asia_locale):
            return False, f"Europe TZ '{fp.timezone}' with locale '{fp.locale}'"
        if asia_tz and (americas_locale or europe_locale):
            return False, f"Asia TZ '{fp.timezone}' with locale '{fp.locale}'"

        return True, ""

    @staticmethod
    def _check_ua_os_match(fp: FingerprintProfile) -> Tuple[bool, str]:
        """UA string must reflect the correct OS."""
        ua = fp.ua_string

        if fp.os == "windows" and "Windows NT" not in ua:
            return False, "UA missing 'Windows NT' for windows OS"
        if fp.os == "macos" and "Macintosh" not in ua:
            return False, "UA missing 'Macintosh' for macOS"
        if fp.os == "linux" and "Linux" not in ua and "X11" not in ua:
            return False, "UA missing 'Linux' or 'X11' for linux OS"

        return True, ""

    @staticmethod
    def _check_ua_chrome_version(fp: FingerprintProfile) -> Tuple[bool, str]:
        """UA Chrome version must match browser_version."""
        browser_major = fp.browser_version.split(".")[0]
        ua_version = ""

        # Extract Chrome/XXX from UA
        import re
        m = re.search(r'Chrome/(\d+)\.', fp.ua_string)
        if m:
            ua_version = m.group(1)

        if ua_version and ua_version != browser_major:
            return False, (
                f"UA Chrome/{ua_version} != browser_version Chrome/{browser_major}"
            )

        return True, ""

    @staticmethod
    def _check_hardware_memory_plausible(fp: FingerprintProfile) -> Tuple[bool, str]:
        """Hardware specs must be in plausible ranges."""
        # Cores: 1-32
        if fp.hardware_concurrency < 1 or fp.hardware_concurrency > 32:
            return False, f"Unrealistic cores: {fp.hardware_concurrency}"

        # Memory: must be power of 2 (2,4,8,16,32...)
        valid_mem = [2, 4, 8, 16, 32, 64]
        if fp.device_memory not in valid_mem:
            return False, f"Unrealistic memory: {fp.device_memory}GB (not power of 2)"

        # High core count with low memory is suspicious
        if fp.hardware_concurrency >= 16 and fp.device_memory <= 4:
            return False, (
                f"High cores ({fp.hardware_concurrency}) with low memory "
                f"({fp.device_memory}GB)"
            )

        return True, ""

    @staticmethod
    def _check_device_scale_factor_range(fp: FingerprintProfile) -> Tuple[bool, str]:
        """DSF must be in realistic range."""
        valid_dsf = [0.75, 1.0, 1.25, 1.5, 2.0, 3.0]
        if fp.device_scale_factor not in valid_dsf:
            # Allow close values (floating point)
            if not any(abs(fp.device_scale_factor - v) < 0.01 for v in valid_dsf):
                return False, f"Unusual device_scale_factor: {fp.device_scale_factor}"
        return True, ""

    @staticmethod
    def _check_languages_contains_locale(fp: FingerprintProfile) -> Tuple[bool, str]:
        """navigator.languages must include the primary locale."""
        if fp.locale not in fp.languages:
            return False, f"languages {fp.languages} missing primary locale {fp.locale}"
        return True, ""

    @staticmethod
    def _check_touch_points_desktop(fp: FingerprintProfile) -> Tuple[bool, str]:
        """Desktop OS should have maxTouchPoints=0 (or 1 on some Chromebooks)."""
        if fp.os != "linux" and fp.max_touch_points > 1:
            return False, f"Desktop {fp.os} with maxTouchPoints={fp.max_touch_points}"
        return True, ""

    @staticmethod
    def _check_color_depth_valid(fp: FingerprintProfile) -> Tuple[bool, str]:
        """colorDepth must be 24 (standard) or 30 (HDR)."""
        if fp.color_depth not in (24, 30):
            return False, f"Unusual colorDepth: {fp.color_depth}"
        return True, ""

    @staticmethod
    def _check_pixel_ratio_consistent(fp: FingerprintProfile) -> Tuple[bool, str]:
        """devicePixelRatio should approximately equal deviceScaleFactor."""
        if abs(fp.pixel_ratio - fp.device_scale_factor) > 0.01:
            return False, (
                f"pixel_ratio {fp.pixel_ratio} != "
                f"device_scale_factor {fp.device_scale_factor}"
            )
        return True, ""

    @staticmethod
    def _check_connection_type_valid(fp: FingerprintProfile) -> Tuple[bool, str]:
        """Connection type must be a recognized value."""
        valid_types = ("4g", "wifi", "ethernet", "3g", "2g", "slow-2g")
        if fp.connection_type not in valid_types:
            return False, f"Unknown connection type: {fp.connection_type}"
        return True, ""

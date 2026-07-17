"""Session-level browser fingerprint generation and injection (L6).

Generates internally-consistent fingerprint profiles sampled from
real-world device distributions, then injects the corresponding JS
patches into L3/L4 browser sessions.

Key components:
- profile: FingerprintProfile dataclass with all detectable dimensions
- generator: Distribution-aware profile sampler
- canvas: Canvas 2D fingerprint noise injection
- audio: AudioContext fingerprint noise injection
- fonts: Font enumeration spoofing
- consistency: Internal consistency validation rules
"""

from cf_bypass.fingerprint.profile import FingerprintProfile
from cf_bypass.fingerprint.generator import FingerprintGenerator
from cf_bypass.fingerprint.canvas import CanvasNoiseInjector, CANVAS_NOISE_SCRIPT
from cf_bypass.fingerprint.audio import AudioNoiseInjector, AUDIO_NOISE_SCRIPT
from cf_bypass.fingerprint.fonts import FontSpoofer, FONT_SPOOF_SCRIPT
from cf_bypass.fingerprint.consistency import ConsistencyValidator

__all__ = [
    "FingerprintProfile",
    "FingerprintGenerator",
    "CanvasNoiseInjector",
    "CANVAS_NOISE_SCRIPT",
    "AudioNoiseInjector",
    "AUDIO_NOISE_SCRIPT",
    "FontSpoofer",
    "FONT_SPOOF_SCRIPT",
    "ConsistencyValidator",
]

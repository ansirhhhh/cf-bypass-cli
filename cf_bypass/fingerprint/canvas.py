"""Canvas 2D fingerprint noise injection.

Canvas fingerprinting is the #1 technique used by FingerprintJS and
DataDome. It works by:
1. Rendering text + shapes to an offscreen <canvas>
2. Calling toDataURL() or getImageData() to get pixel data
3. Hashing the result — different GPU/driver/OS combos produce
   slightly different anti-aliasing, producing a unique hash.

Our defense: add 1-2 bits of noise to strategically chosen pixels
on every toDataURL() / getImageData() call. This changes the hash
while being invisible to the human eye (< 0.01% pixel difference).

Algorithm modes:
- "subtle": modify 2-3 pixels per call (default, undetectable)
- "moderate": modify 5-8 pixels per call
- "aggressive": modify 15-20 pixels per call (may be detectable)
"""

import random
from cf_bypass.logging_config import get_logger

logger = get_logger("fingerprint.canvas")

# ======================================================================
# JS injection script
# ======================================================================

CANVAS_NOISE_SCRIPT_TEMPLATE = """
(function() {{
    'use strict';
    const SEED = {seed};
    const MODE = '{mode}';
    let counter = 0;

    // Determine how many pixels to modify per call
    function getNoiseCount() {{
        switch (MODE) {{
            case 'subtle':    return 2 + (SEED % 2);
            case 'moderate':  return 5 + (SEED % 4);
            case 'aggressive':return 12 + (SEED % 8);
            default:          return 2 + (SEED % 2);
        }}
    }}

    // Simple deterministic pseudo-random based on seed + counter
    function seededRand(max) {{
        const x = Math.sin(SEED * 12345.6789 + counter * 0.1) * 10000;
        return Math.floor((x - Math.floor(x)) * max);
    }}

    // Apply noise to pixel data in-place
    function applyNoise(data, width, height) {{
        const count = getNoiseCount();
        for (let i = 0; i < count; i++) {{
            const pixelIdx = seededRand(width * height);
            const offset = pixelIdx * 4;
            if (offset + 3 < data.length) {{
                // Flip the LSB of R, G, or B (cycles per call)
                const channel = (counter + i) % 3;
                data[offset + channel] ^= 1;
            }}
            counter++;
        }}
    }}

    // ---- toDataURL patch ----
    const origToDataURL = HTMLCanvasElement.prototype.toDataURL;
    HTMLCanvasElement.prototype.toDataURL = function(...args) {{
        try {{
            const ctx = this.getContext('2d', {{ willReadFrequently: true }});
            if (ctx) {{
                const w = this.width || 300;
                const h = this.height || 150;
                const imageData = ctx.getImageData(0, 0, w, h);
                applyNoise(imageData.data, w, h);
                ctx.putImageData(imageData, 0, 0);
            }}
        }} catch(e) {{ /* silently ignore */ }}
        return origToDataURL.apply(this, args);
    }};

    // ---- getImageData patch (some detectors use this directly) ----
    const origGetImageData = CanvasRenderingContext2D.prototype.getImageData;
    CanvasRenderingContext2D.prototype.getImageData = function(...args) {{
        const result = origGetImageData.apply(this, args);
        try {{
            applyNoise(result.data, result.width, result.height);
        }} catch(e) {{ /* silently ignore */ }}
        return result;
    }};

    // ---- toBlob patch ----
    const origToBlob = HTMLCanvasElement.prototype.toBlob;
    HTMLCanvasElement.prototype.toBlob = function(callback, ...args) {{
        try {{
            const ctx = this.getContext('2d', {{ willReadFrequently: true }});
            if (ctx) {{
                const w = this.width || 300;
                const h = this.height || 150;
                const imageData = ctx.getImageData(0, 0, w, h);
                applyNoise(imageData.data, w, h);
                ctx.putImageData(imageData, 0, 0);
            }}
        }} catch(e) {{}}
        return origToBlob.call(this, callback, ...args);
    }};
}})();
"""

CANVAS_NOISE_SCRIPT = CANVAS_NOISE_SCRIPT_TEMPLATE.format(seed=0, mode="subtle")


class CanvasNoiseInjector:
    """Manage Canvas 2D fingerprint noise injection.

    Usage::

        injector = CanvasNoiseInjector(seed=12345, mode="subtle")
        script = injector.get_script()
        await page.evaluate(script)
    """

    def __init__(
        self,
        seed: int = 0,
        mode: str = "subtle",
    ):
        """Initialize canvas noise injector.

        Args:
            seed: 16-bit noise seed (different per session).
            mode: "subtle", "moderate", or "aggressive".
        """
        self.seed = seed
        self.mode = mode

    def get_script(self) -> str:
        """Return the JS injection script with current seed and mode."""
        return CANVAS_NOISE_SCRIPT_TEMPLATE.format(
            seed=self.seed,
            mode=self.mode,
        )

    @staticmethod
    def get_default_script() -> str:
        """Return a default script (seed=0, mode='subtle')."""
        return CANVAS_NOISE_SCRIPT

    async def inject(self, page) -> bool:
        """Inject canvas noise script into a browser page.

        Args:
            page: Playwright or nodriver page object.

        Returns:
            True if injection succeeded.
        """
        try:
            script = self.get_script()
            await page.evaluate(script)
            logger.debug(
                f"Canvas noise injected: seed={self.seed}, mode={self.mode}"
            )
            return True
        except Exception as exc:
            logger.debug(f"Canvas noise injection failed: {exc}")
            return False

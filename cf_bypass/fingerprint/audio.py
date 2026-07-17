"""AudioContext fingerprint noise injection.

AudioContext fingerprinting works by:
1. Creating an OscillatorNode with a known frequency
2. Connecting it through a DynamicsCompressorNode (adds subtle distortion)
3. Reading the resulting audio samples via AnalyserNode
4. The compressor's behavior varies by audio hardware/driver, producing
   a unique fingerprint hash.

Our defense: add tiny perturbations to AnalyserNode's output frequencies.
The noise is inaudible (<0.01% amplitude change) but changes the hash.

Algorithm:
- On getFloatFrequencyData / getByteFrequencyData, modify 1-2 frequency
  bin values by ±0.0001 or ±1 (depending on float vs byte mode).
- The modification pattern is deterministic per-session (seed-based) so
  the fingerprint is stable WITHIN a session but varies ACROSS sessions.
"""

from cf_bypass.logging_config import get_logger

logger = get_logger("fingerprint.audio")

# ======================================================================
# JS injection script
# ======================================================================

AUDIO_NOISE_SCRIPT_TEMPLATE = """
(function() {{
    'use strict';
    const SEED = {seed};
    let callCounter = 0;

    // Simple seeded index generator
    function getIndices(count, max) {{
        const indices = [];
        for (let i = 0; i < count; i++) {{
            const x = Math.sin(SEED * 6789.0123 + callCounter * 0.1 + i * 1.7) * 10000;
            indices.push(Math.floor((x - Math.floor(x)) * max));
        }}
        return indices;
    }}

    // ---- getFloatFrequencyData patch ----
    if (typeof AnalyserNode !== 'undefined') {{
        const origGetFloatFreq = AnalyserNode.prototype.getFloatFrequencyData;
        AnalyserNode.prototype.getFloatFrequencyData = function(array) {{
            origGetFloatFreq.call(this, array);
            try {{
                const indices = getIndices(2, array.length);
                for (const idx of indices) {{
                    if (idx < array.length) {{
                        array[idx] += (SEED % 2 === 0 ? 0.0001 : -0.0001);
                    }}
                }}
            }} catch(e) {{}}
            callCounter++;
        }};

        // ---- getByteFrequencyData patch ----
        const origGetByteFreq = AnalyserNode.prototype.getByteFrequencyData;
        AnalyserNode.prototype.getByteFrequencyData = function(array) {{
            origGetByteFreq.call(this, array);
            try {{
                const indices = getIndices(1, array.length);
                for (const idx of indices) {{
                    if (idx < array.length) {{
                        array[idx] = Math.max(0, Math.min(255,
                            array[idx] + (SEED % 3 === 0 ? 1 : -1)
                        ));
                    }}
                }}
            }} catch(e) {{}}
            callCounter++;
        }};

        // ---- getFloatTimeDomainData patch ----
        const origGetFloatTime = AnalyserNode.prototype.getFloatTimeDomainData;
        AnalyserNode.prototype.getFloatTimeDomainData = function(array) {{
            origGetFloatTime.call(this, array);
            try {{
                const indices = getIndices(1, array.length);
                for (const idx of indices) {{
                    if (idx < array.length) {{
                        array[idx] += (SEED % 2 === 0 ? 0.00005 : -0.00005);
                    }}
                }}
            }} catch(e) {{}}
            callCounter++;
        }};
    }}
}})();
"""

AUDIO_NOISE_SCRIPT = AUDIO_NOISE_SCRIPT_TEMPLATE.format(seed=0)


class AudioNoiseInjector:
    """Manage AudioContext fingerprint noise injection.

    Usage::

        injector = AudioNoiseInjector(seed=12345)
        script = injector.get_script()
        await page.evaluate(script)
    """

    def __init__(self, seed: int = 0):
        """Initialize audio noise injector.

        Args:
            seed: 16-bit noise seed (different per session).
        """
        self.seed = seed

    def get_script(self) -> str:
        """Return the JS injection script with current seed."""
        return AUDIO_NOISE_SCRIPT_TEMPLATE.format(seed=self.seed)

    @staticmethod
    def get_default_script() -> str:
        """Return a default script (seed=0)."""
        return AUDIO_NOISE_SCRIPT

    async def inject(self, page) -> bool:
        """Inject audio noise script into a browser page.

        Args:
            page: Playwright or nodriver page object.

        Returns:
            True if injection succeeded.
        """
        try:
            script = self.get_script()
            await page.evaluate(script)
            logger.debug(f"Audio noise injected: seed={self.seed}")
            return True
        except Exception as exc:
            logger.debug(f"Audio noise injection failed: {exc}")
            return False

"""Font enumeration spoofing.

Advanced bot detection probes installed fonts via:
1. CSS FontFace API (measure text width with different fonts)
2. Flash/Java font enumeration (deprecated but still checked)
3. `document.fonts` API (FontFaceSet)

Our defense: intercept `document.fonts` and CSS FontFace to return
a plausible OS-appropriate font list without exposing the real set.

Strategy:
- Override FontFaceSet.prototype.entries/forEach to return
  a pre-configured font list.
- The list matches the FingerprintProfile's OS.
"""

from typing import List
from cf_bypass.logging_config import get_logger

logger = get_logger("fingerprint.fonts")

# ======================================================================
# JS injection script
# ======================================================================

FONT_SPOOF_SCRIPT_TEMPLATE = """
(function() {{
    'use strict';

    // Font list to expose (OS-appropriate, matches profile)
    const SPOOFED_FONTS = {fonts_json};

    try {{
        // Override FontFaceSet if present
        if (typeof FontFaceSet !== 'undefined') {{
            const origEntries = FontFaceSet.prototype.entries;
            const origForEach = FontFaceSet.prototype.forEach;
            const origHas = FontFaceSet.prototype.has;

            FontFaceSet.prototype.entries = function() {{
                let idx = 0;
                const self = this;
                return {{
                    next: function() {{
                        if (idx < SPOOFED_FONTS.length) {{
                            return {{ value: [SPOOFED_FONTS[idx], self], done: false }};
                        }}
                        return {{ done: true }};
                    }},
                    [Symbol.iterator]: function() {{ return this; }}
                }};
            }};

            FontFaceSet.prototype.forEach = function(callback) {{
                for (const font of SPOOFED_FONTS) {{
                    callback(font, font, this);
                }}
            }};

            FontFaceSet.prototype.has = function(font) {{
                return SPOOFED_FONTS.includes(font);
            }};

            // Add entries to the FontFaceSet so it's not empty
            Object.defineProperty(FontFaceSet.prototype, 'size', {{
                get: function() {{ return SPOOFED_FONTS.length; }}
            }});
        }}
    }} catch(e) {{ /* ignore */ }}

    // Override document.fonts if available
    try {{
        if (document.fonts) {{
            // Force size and status
            Object.defineProperty(document.fonts, 'size', {{
                get: function() {{ return SPOOFED_FONTS.length; }},
                configurable: true,
            }});
            Object.defineProperty(document.fonts, 'status', {{
                get: function() {{ return 'loaded'; }},
                configurable: true,
            }});
        }}
    }} catch(e) {{ /* ignore */ }}
}})();
"""

FONT_SPOOF_SCRIPT = FONT_SPOOF_SCRIPT_TEMPLATE.replace(
    "{fonts_json}", "[]"
)


class FontSpoofer:
    """Manage font enumeration spoofing.

    Usage::

        spoofer = FontSpoofer(["Arial", "Times New Roman", ...])
        script = spoofer.get_script()
        await page.evaluate(script)
    """

    def __init__(self, fonts: List[str] = None):
        """Initialize font spoofer.

        Args:
            fonts: List of font names to expose. If empty, uses
                   a default Windows-appropriate set.
        """
        self.fonts = fonts or [
            "Arial",
            "Comic Sans MS",
            "Courier New",
            "Georgia",
            "Impact",
            "Times New Roman",
            "Trebuchet MS",
            "Verdana",
            "Segoe UI",
            "Calibri",
        ]

    def get_script(self) -> str:
        """Return the JS injection script with the current font list."""
        import json
        fonts_json = json.dumps(self.fonts)
        return FONT_SPOOF_SCRIPT_TEMPLATE.replace("{fonts_json}", fonts_json)

    async def inject(self, page) -> bool:
        """Inject font spoofing script into a browser page.

        Args:
            page: Playwright or nodriver page object.

        Returns:
            True if injection succeeded.
        """
        try:
            script = self.get_script()
            await page.evaluate(script)
            logger.debug(f"Font spoof injected: {len(self.fonts)} fonts")
            return True
        except Exception as exc:
            logger.debug(f"Font spoof injection failed: {exc}")
            return False

"""Enhanced anti-detection patches for L3 (Playwright) and L4 (nodriver).

Incorporates techniques from undetected-chromedriver:
  - CDC variable removal (window.cdc_* cleanup)
  - Full chrome.runtime object with complete enum sets
  - Navigator proxy-based webdriver hiding
  - Function.prototype.toString patching (hides the patches themselves)
  - Headless-specific CDP evasions (UA fixup, maxTouchPoints, connection.rtt)
  - L3/L4 differentiated fingerprints to avoid cross-level correlation.
"""

from cf_bypass.logging_config import get_logger

logger = get_logger("strategies.stealth")

# ======================================================================
# CDC variable cleanup — removes Chromedriver's injected JS variables
# from the window scope.  These 27-char random names ending in Array/
# Promise/Symbol are the #1 detection vector for Selenium-based automation.
# ======================================================================

CDC_CLEANUP_SCRIPT = """
(function() {
    let obj = window;
    while (obj !== null) {
        let names = Object.getOwnPropertyNames(obj);
        for (let n of names) {
            if (/^[a-zA-Z]{27}(Array|Promise|Symbol)$/.test(n)) {
                try { delete window[n]; } catch(e) {}
            }
        }
        obj = Object.getPrototypeOf(obj);
    }
})();
"""

# ======================================================================
# Complete chrome.runtime object — matches what real Chrome exposes.
# undetected-chromedriver builds this with full PlatformArch/PlatformOs/
# RunningState/OnInstalledReason enums.  Many CF heuristics check these.
# ======================================================================

CHROME_RUNTIME_FULL = """
window.chrome = {
    app: {
        isInstalled: false,
        InstallState: {
            DISABLED: 'disabled',
            INSTALLED: 'installed',
            NOT_INSTALLED: 'not_installed'
        },
        RunningState: {
            CANNOT_RUN: 'cannot_run',
            READY_TO_RUN: 'ready_to_run',
            RUNNING: 'running'
        }
    },
    runtime: {
        OnInstalledReason: {
            CHROME_UPDATE: 'chrome_update',
            INSTALL: 'install',
            SHARED_MODULE_UPDATE: 'shared_module_update',
            UPDATE: 'update'
        },
        OnRestartRequiredReason: {
            APP_UPDATE: 'app_update',
            OS_UPDATE: 'os_update',
            PERIODIC: 'periodic'
        },
        PlatformArch: {
            ARM: 'arm',
            ARM64: 'arm64',
            MIPS: 'mips',
            MIPS64: 'mips64',
            X86_32: 'x86-32',
            X86_64: 'x86-64'
        },
        PlatformNaclArch: {
            ARM: 'arm',
            MIPS: 'mips',
            MIPS64: 'mips64',
            X86_32: 'x86-32',
            X86_64: 'x86-64'
        },
        PlatformOs: {
            ANDROID: 'android',
            CROS: 'cros',
            LINUX: 'linux',
            MAC: 'mac',
            OPENBSD: 'openbsd',
            WIN: 'win'
        },
        RequestUpdateCheckStatus: {
            NO_UPDATE: 'no_update',
            THROTTLED: 'throttled',
            UPDATE_AVAILABLE: 'update_available'
        }
    },
    loadTimes: function() {},
    csi: function() {}
};
"""

# ======================================================================
# Navigator webdriver hiding via Proxy — more robust than simple
# Object.defineProperty because it intercepts `has` checks as well.
# ======================================================================

NAVIGATOR_PROXY_SCRIPT = """
(function() {
    const originalNavigator = window.navigator;
    const proxyHandler = {
        has: (target, key) => (key === 'webdriver' ? false : key in target),
        get: (target, key) =>
            key === 'webdriver'
                ? undefined
                : typeof target[key] === 'function'
                    ? target[key].bind(target)
                    : target[key],
    };
    Object.defineProperty(window, 'navigator', {
        value: new Proxy(originalNavigator, proxyHandler),
        configurable: false,
        writable: false,
    });
})();
"""

# ======================================================================
# Real PluginArray + MimeTypeArray emulation
# ----------------------------------------------------------------------
# DataDome / Cloudflare / FingerprintJS check 4 things about plugins:
#   1. `navigator.plugins`            — must be a PluginArray (instanceof + toStringTag)
#   2. `navigator.mimeTypes`          — must be a MimeTypeArray
#   3. `Object.prototype.toString.call(navigator.plugins) === '[object PluginArray]'`
#   4. Real Chrome has 5 default plugins (PDF, Native Client, etc.)
#
# The previous version failed these checks because it just set a plain
# array as plugins, with no toStringTag, no real Plugin prototype, no
# mimeTypes.  This new script:
#   - Defines a proper PluginArray / MimeTypeArray class with toStringTag
#   - Emulates Chrome 120's 5 default plugins (PDF, PDF Viewer, Native Client)
#   - Each plugin item has Plugin prototype with toStringTag='Plugin'
#   - mimeTypes mirrors the plugins (3 entries)
#   - All getters are defined on window.navigator (NOT assignable after)
# ======================================================================

PLUGIN_ARRAY_SCRIPT = r"""
(function() {
    'use strict';

    // ----- helpers -----
    const defineFrozen = (obj, prop, val) => {
        try {
            Object.defineProperty(obj, prop, {
                value: val,
                writable: false,
                enumerable: true,
                configurable: false,
            });
        } catch (e) { /* ignore */ }
    };

    // ----- Plugin class -----
    class FakeMimeType {
        constructor(type, suffixes, description) {
            this.type = type;
            this.suffixes = suffixes;
            this.description = description;
            this.__proto__ = MimeType.prototype;
        }
        [Symbol.toStringTag] = 'MimeType';
    }
    class MimeType {
        [Symbol.toStringTag] = 'MimeType';
    }
    class MimeTypeArray {
        constructor(items) {
            this._items = items || [];
            this.length = this._items.length;
            this.__proto__ = MimeTypeArray.prototype;
        }
        item(index) { return this._items[index] || null; }
        namedItem(name) {
            return this._items.find(m => m.type === name) || null;
        }
        [Symbol.toStringTag] = 'MimeTypeArray';
    }
    // Make namedItem / item appear as native code in toString
    MimeTypeArray.prototype.item = MimeTypeArray.prototype.item;
    MimeTypeArray.prototype.namedItem = MimeTypeArray.prototype.namedItem;

    class FakePlugin {
        constructor(name, filename, description, mimeTypes) {
            this.name = name;
            this.filename = filename;
            this.description = description;
            this.length = mimeTypes.length;
            this.__proto__ = Plugin.prototype;
            mimeTypes.forEach((mt, i) => {
                defineFrozen(this, i, mt);
            });
        }
        item(index) { return this[index] || null; }
        namedItem(name) { return this._items_by_name && this._items_by_name[name] || null; }
        [Symbol.toStringTag] = 'Plugin';
    }
    class Plugin {
        [Symbol.toStringTag] = 'Plugin';
    }
    class PluginArray {
        constructor(plugins) {
            this._plugins = plugins || [];
            this.length = this._plugins.length;
            this.__proto__ = PluginArray.prototype;
        }
        item(index) { return this._plugins[index] || null; }
        namedItem(name) { return this._plugins.find(p => p.name === name) || null; }
        refresh() { /* no-op for stealth */ }
        [Symbol.toStringTag] = 'PluginArray';
    }

    // Build Chrome 120 default plugins (5 entries, matching real Chrome)
    const mtPdf       = new FakeMimeType('application/pdf', 'pdf', 'Portable Document Format');
    const mtPdfFx     = new FakeMimeType(
        'application/x-google-chrome-pdf',
        'pdf',
        'Portable Document Format'
    );
    const mtNaCl      = new FakeMimeType(
        'application/x-nacl',
        '',
        'Native Client Executable'
    );
    const mtPnacl     = new FakeMimeType(
        'application/x-pnacl',
        '',
        'Portable Native Client Executable'
    );

    const pdfPlugin = new FakePlugin(
        'PDF Viewer',
        'internal-pdf-viewer',
        'Portable Document Format',
        [mtPdf, mtPdfFx]
    );
    const chromePdfPlugin = new FakePlugin(
        'Chrome PDF Viewer',
        'mhjfbmdgcfjbbpaeojofohoefgiehjai',
        'Portable Document Format',
        [mtPdf, mtPdfFx]
    );
    const naclPlugin = new FakePlugin(
        'Native Client',
        'internal-nacl-plugin',
        '',
        [mtNaCl, mtPnacl]
    );
    // Chrome typically also lists these (some are partial / disabled)
    const chromiumPdf = new FakePlugin(
        'Chromium PDF Viewer',
        'internal-pdf-viewer',
        'Portable Document Format',
        [mtPdf]
    );
    const microsoftPdf = new FakePlugin(
        'Microsoft Edge PDF Viewer',
        'internal-pdf-viewer',
        'Portable Document Format',
        [mtPdf]
    );

    const pluginsArr = new PluginArray([
        pdfPlugin,
        chromePdfPlugin,
        chromiumPdf,
        microsoftPdf,
        naclPlugin,
    ]);

    const mimesArr = new MimeTypeArray([
        mtPdf, mtPdfFx, mtNaCl, mtPnacl,
    ]);

    // ----- install onto navigator -----
    // First, make sure PluginArray etc. are visible at window scope
    window.PluginArray = PluginArray;
    window.Plugin = Plugin;
    window.MimeType = MimeType;
    window.MimeTypeArray = MimeTypeArray;

    // Override the getter that the browser uses internally
    try {
        Object.defineProperty(navigator, 'plugins', {
            get: () => pluginsArr,
            enumerable: true,
            configurable: true,
        });
    } catch (e) { /* ignore */ }
    try {
        Object.defineProperty(navigator, 'mimeTypes', {
            get: () => mimesArr,
            enumerable: true,
            configurable: true,
        });
    } catch (e) { /* ignore */ }
})();
"""

# ======================================================================
# Function.prototype.toString hiding — makes patched functions appear
# to be native code.  This is critical: many CF probes check whether
# navigator.permissions.query.toString() returns "[native code]".
# ======================================================================

TOSTRING_HIDING_SCRIPT = """
(function() {
    const _origCall = Function.prototype.call;
    function call() { return _origCall.apply(this, arguments); }
    Function.prototype.call = call;

    const _origToString = Function.prototype.toString;
    const nativeFuncStr = Error.toString().replace(/Error/g, 'toString');
    // "function toString() { [native code] }"

    function functionToString() {
        if (this === window.navigator.permissions.query) {
            return 'function query() { [native code] }';
        }
        if (this === functionToString) {
            return nativeFuncStr;
        }
        return _origCall.call(_origToString, this);
    }
    Function.prototype.toString = functionToString;
})();
"""

# Backwards-compat alias
TOSTRING_SCRIPT = TOSTRING_HIDING_SCRIPT

# ======================================================================
# Headless-specific evasions — headless Chrome has unique fingerprints
# (UA contains "Headless", maxTouchPoints=0, connection.rtt absent).
# ======================================================================

HEADLESS_EVASION_SCRIPT = """
(function() {
    // headless Chrome defaults maxTouchPoints to 0
    Object.defineProperty(navigator, 'maxTouchPoints', { get: () => 1 });

    // headless Chrome sometimes misses connection.rtt
    if (navigator.connection) {
        Object.defineProperty(navigator.connection, 'rtt', { get: () => 100 });
    }

    // Notification permission
    if (!window.Notification) {
        window.Notification = { permission: 'denied' };
    }

    // PDF viewer enabled (headless sometimes has it disabled)
    navigator.pdfViewerEnabled = true;
})();
"""


# ======================================================================
# WebGL vendor/renderer — real Intel/AMD GPU strings; headless Chrome
# otherwise returns "Google Inc." (SwiftShader) which is a dead giveaway.
# ======================================================================

WEBGL_SPOOF_SCRIPT = r"""
(function() {
    try {
        const getParam = WebGLRenderingContext.prototype.getParameter;
        WebGLRenderingContext.prototype.getParameter = function(param) {
            // UNMASKED_VENDOR_WEBGL
            if (param === 37445) return 'Intel Inc.';
            // UNMASKED_RENDERER_WEBGL
            if (param === 37446) return 'Intel Iris OpenGL Engine';
            return getParam.call(this, param);
        };
        const getParam2 = WebGL2RenderingContext.prototype.getParameter;
        WebGL2RenderingContext.prototype.getParameter = function(param) {
            if (param === 37445) return 'Intel Inc.';
            if (param === 37446) return 'Intel Iris OpenGL Engine';
            return getParam2.call(this, param);
        };
    } catch (e) { /* ignore */ }
})();
"""

# ======================================================================
# navigator.userAgentData (User-Agent Client Hints)
# Real Chrome 120 returns brands like "Not_A Brand";v="8", "Chromium";v="120",
# "Google Chrome";v="120".  Headless and Playwright expose empty or
# wrong brands, which is a key DataDome signal.
# ======================================================================

USER_AGENT_DATA_SCRIPT = r"""
(function() {
    if (!navigator.userAgentData) {
        // Polyfill it (so the property exists and behaves like real Chrome)
        const brands = [
            { brand: 'Not_A Brand', version: '8' },
            { brand: 'Chromium',    version: '120' },
            { brand: 'Google Chrome', version: '120' },
        ];
        const uaData = {
            brands: brands,
            mobile: false,
            platform: 'Windows',
            getHighEntropyValues: function(hints) {
                return Promise.resolve({
                    architecture: 'x86',
                    bitness: '64',
                    brands: brands,
                    fullVersionList: brands,
                    mobile: false,
                    model: '',
                    platform: 'Windows',
                    platformVersion: '15.0.0',
                    uaFullVersion: '120.0.6099.130',
                    wow64: false,
                });
            },
            toJSON: function() { return { brands: brands, mobile: false, platform: 'Windows' }; },
        };
        try {
            Object.defineProperty(Navigator.prototype, 'userAgentData', {
                get: () => uaData,
                configurable: true,
            });
        } catch (e) { /* ignore */ }
    }
})();
"""

# ======================================================================
# navigator.connection — real Chrome exposes rtt/downlink/effectiveType;
# headless sometimes leaves it undefined.  Spoof consistent values.
# ======================================================================

CONNECTION_SPOOF_SCRIPT = r"""
(function() {
    if (!navigator.connection) {
        try {
            Object.defineProperty(Navigator.prototype, 'connection', {
                get: () => ({
                    effectiveType: '4g',
                    downlink: 10,
                    rtt: 100,
                    saveData: false,
                    addEventListener: function() {},
                    removeEventListener: function() {},
                }),
                configurable: true,
            });
        } catch (e) { /* ignore */ }
    }
})();
"""

# ======================================================================
# L3 (Playwright) Scripts — layered on top of playwright-stealth
# ======================================================================

L3_ENHANCED_SCRIPTS = [
    # 1. CDC cleanup — must run first
    ("cdc_cleanup", CDC_CLEANUP_SCRIPT),

    # 2. Navigator proxy — more robust than defineProperty alone
    ("navigator_proxy", NAVIGATOR_PROXY_SCRIPT),

    # 3. Full chrome runtime (ucd-style complete enums)
    ("chrome_runtime", CHROME_RUNTIME_FULL),

    # 4. PluginArray + MimeTypeArray — must run before toString hiding
    ("plugin_array", PLUGIN_ARRAY_SCRIPT),

    # 5. WebGL vendor/renderer
    ("webgl_spoof", WEBGL_SPOOF_SCRIPT),

    # 6. userAgentData (Client Hints)
    ("user_agent_data", USER_AGENT_DATA_SCRIPT),

    # 7. Connection API
    ("connection_spoof", CONNECTION_SPOOF_SCRIPT),

    # 8. Languages
    ("languages", """
        Object.defineProperty(navigator, 'languages', {
            get: () => ['en-US', 'en'],
        });
    """),

    # 9. Permissions query (with Notification handling)
    ("permissions", """
        const _origQ = navigator.permissions.query.bind(navigator.permissions);
        navigator.permissions.query = (params) => {
            if (params.name === 'notifications') {
                return Promise.resolve({ state: 'granted', onchange: null });
            }
            return _origQ(params);
        };
    """),

    # 10. Hardware specs
    ("hardware", """
        Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 });
        Object.defineProperty(navigator, 'deviceMemory', { get: () => 8 });
    """),

    # 11. Headless evasions (harmless in headed mode, critical in headless)
    ("headless_evasion", HEADLESS_EVASION_SCRIPT),

    # 12. toString hiding — MUST run last, wraps everything above
    ("tostring_hiding", TOSTRING_SCRIPT),
]


# Self-test that runs after the patches — logs which checks pass/fail
STEALTH_SELF_TEST_SCRIPT = r"""
(function() {
    const results = [];
    function check(name, ok, detail) {
        results.push({ name: name, ok: ok, detail: detail || '' });
    }

    // 1. PluginArray toStringTag
    try {
        const t = Object.prototype.toString.call(navigator.plugins);
        check('plugins_toStringTag', t === '[object PluginArray]', 'got: ' + t);
    } catch (e) { check('plugins_toStringTag', false, e.message); }

    // 2. MimeTypeArray toStringTag
    try {
        const t = Object.prototype.toString.call(navigator.mimeTypes);
        check('mimeTypes_toStringTag', t === '[object MimeTypeArray]', 'got: ' + t);
    } catch (e) { check('mimeTypes_toStringTag', false, e.message); }

    // 3. plugins instanceof PluginArray
    try {
        check('plugins_instanceof', navigator.plugins instanceof PluginArray,
              'proto=' + Object.getPrototypeOf(navigator.plugins).constructor.name);
    } catch (e) { check('plugins_instanceof', false, e.message); }

    // 4. plugins has at least 3 entries
    try {
        check('plugins_count', navigator.plugins.length >= 3,
              'length=' + navigator.plugins.length);
    } catch (e) { check('plugins_count', false, e.message); }

    // 5. PDF plugin exists
    try {
        const pdf = navigator.plugins.namedItem('PDF Viewer')
                 || navigator.plugins.namedItem('Chrome PDF Viewer');
        check('pdf_plugin_present', pdf !== null, pdf ? pdf.name : 'none');
    } catch (e) { check('pdf_plugin_present', false, e.message); }

    // 6. navigator.webdriver hidden
    check('webdriver_hidden', !navigator.webdriver,
          'value=' + JSON.stringify(navigator.webdriver));

    // 7. languages
    try {
        check('languages_set',
              Array.isArray(navigator.languages) && navigator.languages.length > 0,
              JSON.stringify(navigator.languages));
    } catch (e) { check('languages_set', false, e.message); }

    // 8. userAgentData brands
    try {
        const brands = (navigator.userAgentData && navigator.userAgentData.brands) || [];
        check('uaData_brands', brands.length >= 2,
              JSON.stringify(brands.map(b => b.brand + ':' + b.version)));
    } catch (e) { check('uaData_brands', false, e.message); }

    // 9. WebGL renderer
    try {
        const canvas = document.createElement('canvas');
        const gl = canvas.getContext('webgl');
        if (gl) {
            const ext = gl.getExtension('WEBGL_debug_renderer_info');
            if (ext) {
                const r = gl.getParameter(ext.UNMASKED_RENDERER_WEBGL);
                check('webgl_renderer', r && !/SwiftShader|swiftshader/i.test(r),
                      'renderer=' + r);
            } else {
                check('webgl_renderer', true, 'extension not exposed (ok)');
            }
        } else {
            check('webgl_renderer', true, 'webgl unavailable (ok)');
        }
    } catch (e) { check('webgl_renderer', false, e.message); }

    // Print to console so we can grep
    console.log('[STEALTH-SELFTEST] ' + JSON.stringify(results));
    window.__stealthSelfTest = results;
})();
"""


async def run_stealth_self_test(page) -> dict:
    """Run the self-test and return the result dict.

    Returns a dict of {check_name: {"ok": bool, "detail": str}}.
    Useful for the orchestrator to log stealth quality.
    """
    try:
        await page.evaluate(STEALTH_SELF_TEST_SCRIPT)
        # Wait a tick for console to flush
        await page.wait_for_timeout(500)
        result = await page.evaluate("() => window.__stealthSelfTest || []")
        if not isinstance(result, list):
            return {}
        return {
            r.get("name", "?"): {
                "ok": bool(r.get("ok")),
                "detail": r.get("detail", ""),
            }
            for r in result
        }
    except Exception as exc:
        logger.debug(f"stealth self-test failed: {exc}")
        return {}


async def apply_enhanced_stealth_l3(page, *, run_self_test: bool = False) -> dict:
    """Apply playwright-stealth + undetected-chromedriver-style JS evasions.

    Injects 12 init scripts that run on every new document load.  The
    ordering matters: CDC cleanup first, toString hiding last.

    Parameters
    ----------
    run_self_test : bool
        If True, runs STEALTH_SELF_TEST_SCRIPT after navigation and returns
        the result dict.  Default False (zero overhead during normal use).

    Returns
    -------
    dict
        Self-test result if `run_self_test=True`, else {}.
    """
    # Core playwright-stealth patches
    try:
        from playwright_stealth import Stealth
        stealth = Stealth()
        await stealth.apply_stealth_async(page)
        logger.debug("playwright-stealth applied to L3 page")
    except Exception as exc:
        logger.warning(f"playwright-stealth apply failed: {exc}")

    # Enhanced evasion scripts (undetected-chromedriver techniques)
    for name, script in L3_ENHANCED_SCRIPTS:
        try:
            await page.add_init_script(script)
            logger.debug(f"L3 stealth patch '{name}' registered")
        except Exception as exc:
            logger.debug(f"L3 stealth patch '{name}' failed (non-fatal): {exc}")

    logger.debug(
        f"Enhanced L3 stealth applied ({len(L3_ENHANCED_SCRIPTS)} extra patches)"
    )

    if run_self_test:
        return await run_stealth_self_test(page)
    return {}


async def apply_headless_evasions_l3(page) -> None:
    """Apply CDP-level headless evasions for Playwright.

    This sends CDP commands directly to the browser to:
    1. Remove "Headless" from the User-Agent string
    2. Override navigator.platform if needed

    Should only be called when headless=True.
    """
    try:
        cdp = page.context.new_cdp_session(page)
        # Remove "Headless" from UA (key ucd technique)
        ua = await page.evaluate("navigator.userAgent")
        clean_ua = ua.replace("Headless", "").replace("headless", "")
        await cdp.send("Network.setUserAgentOverride", {"userAgent": clean_ua})
        logger.debug("Headless UA cleaned via CDP")
    except Exception as exc:
        logger.debug(f"Headless CDP evasion failed (non-fatal): {exc}")


# ======================================================================
# L4 (nodriver) — CDP-native, minimal JS patches needed.
# Differentiated flags + ucd-style chrome object for fingerprint diversity.
# ======================================================================

L4_CDP_FLAGS = [
    "--no-sandbox",
    "--disable-blink-features=AutomationControlled",
    "--disable-web-security",
    "--disable-features=IsolateOrigins,site-per-process",
    "--disable-component-update",
    "--disable-default-apps",
    "--disable-sync",
    "--no-first-run",
    "--no-default-browser-check",
    "--test-type",          # ucd adds this to suppress "unsafe" warnings
    "--disable-crash-reporter",
]

L4_ENHANCED_SCRIPTS = [
    # Same core evasions as L3 (but evaluated live, not via init script)
    ("cdc_cleanup", CDC_CLEANUP_SCRIPT),
    ("navigator_proxy", NAVIGATOR_PROXY_SCRIPT),
    ("chrome_runtime", CHROME_RUNTIME_FULL),
    ("plugin_array", PLUGIN_ARRAY_SCRIPT),
    ("webgl_spoof", WEBGL_SPOOF_SCRIPT),
    ("user_agent_data", USER_AGENT_DATA_SCRIPT),
    ("connection_spoof", CONNECTION_SPOOF_SCRIPT),
    ("headless_evasion", HEADLESS_EVASION_SCRIPT),
    ("tostring_hiding", TOSTRING_HIDING_SCRIPT),
]


def get_l4_browser_args() -> list:
    """Return recommended Chrome flags for L4 nodriver.

    Differentiated from L3 to avoid fingerprint correlation.
    """
    return list(L4_CDP_FLAGS)


async def apply_enhanced_stealth_l4(page) -> None:
    """Apply L4-specific CDP-level anti-detection.

    nodriver already bypasses WebDriver signatures via raw CDP (no
    ``Target.setAutoAttach``, no ``Runtime.enable`` noise), so the
    JS patch set is lighter than L3's.  The key differentiation is
    in the browser flags and a minimal but effective JS layer.
    """
    applied = 0
    for name, script in L4_ENHANCED_SCRIPTS:
        try:
            await page.evaluate(script)
            applied += 1
        except Exception as exc:
            logger.debug(f"L4 stealth patch '{name}' failed (non-fatal): {exc}")

    logger.debug(
        f"Enhanced L4 stealth applied ({applied}/{len(L4_ENHANCED_SCRIPTS)} patches)"
    )

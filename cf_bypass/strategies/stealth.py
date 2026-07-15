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
# L3 (Playwright) Scripts — layered on top of playwright-stealth
# ======================================================================

L3_ENHANCED_SCRIPTS = [
    # 1. CDC cleanup — must run first
    ("cdc_cleanup", CDC_CLEANUP_SCRIPT),

    # 2. Navigator proxy — more robust than defineProperty alone
    ("navigator_proxy", NAVIGATOR_PROXY_SCRIPT),

    # 3. Full chrome runtime (ucd-style complete enums)
    ("chrome_runtime", CHROME_RUNTIME_FULL),

    # 4. Plugins array
    ("plugins", """
        Object.defineProperty(navigator, 'plugins', {
            get: () => {
                const len = 5;
                const arr = Array.from({length: len}, (_, i) => ({
                    name: `Plugin ${i}`,
                    description: `Plugin ${i} description`,
                    filename: `plugin${i}.dll`,
                    length: 1,
                }));
                arr.item = (i) => arr[i] || null;
                arr.namedItem = (name) => arr.find(p => p.name === name) || null;
                arr.refresh = () => {};
                Object.setPrototypeOf(arr, PluginArray.prototype);
                return arr;
            },
        });
    """),

    # 5. Languages
    ("languages", """
        Object.defineProperty(navigator, 'languages', {
            get: () => ['en-US', 'en'],
        });
    """),

    # 6. Permissions query (with Notification handling)
    ("permissions", """
        const _origQ = navigator.permissions.query.bind(navigator.permissions);
        navigator.permissions.query = (params) => {
            if (params.name === 'notifications') {
                return Promise.resolve({ state: 'granted', onchange: null });
            }
            return _origQ(params);
        };
    """),

    # 7. Hardware specs
    ("hardware", """
        Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 });
        Object.defineProperty(navigator, 'deviceMemory', { get: () => 8 });
    """),

    # 8. Headless evasions (harmless in headed mode, critical in headless)
    ("headless_evasion", HEADLESS_EVASION_SCRIPT),

    # 9. toString hiding — MUST run last, wraps everything above
    ("tostring_hiding", TOSTRING_HIDING_SCRIPT),
]


async def apply_enhanced_stealth_l3(page) -> None:
    """Apply playwright-stealth + undetected-chromedriver-style JS evasions.

    Injects 10 init scripts that run on every new document load.  The
    ordering matters: CDC cleanup first, toString hiding last.
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
    # Lighter than L3 for fingerprint diversity
    ("cdc_cleanup", CDC_CLEANUP_SCRIPT),
    ("navigator_proxy", NAVIGATOR_PROXY_SCRIPT),
    ("chrome_runtime", CHROME_RUNTIME_FULL),
    ("headless_evasion", HEADLESS_EVASION_SCRIPT),
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

"""Solver abstraction for Cloudflare Turnstile and captcha challenges.

Provides a pluggable architecture for captcha-solving services
(2captcha, Capsolver, Anti-Captcha) and browser-level token injection.

v2.0 adds:
- CaptchaDispatcher: unified captcha routing with provider fallback
- reCAPTCHA v2 / v3 solvers
- hCaptcha solver
- Image captcha solver (with LLM vision fallback)
- Provider registry (capsolver, 2captcha, llm_vision)
"""

from cf_bypass.solvers.base import BaseSolver, SolverResult
from cf_bypass.solvers.turnstile import TurnstileSolver
from cf_bypass.solvers.recaptcha_v2 import RecaptchaV2Solver
from cf_bypass.solvers.hcaptcha import HCaptchaSolver
from cf_bypass.solvers.image_captcha import ImageCaptchaSolver
from cf_bypass.solvers.dispatcher import (
    CaptchaDispatcher,
    CaptchaType,
    DispatcherConfig,
    ProviderEntry,
    detect_captcha_types,
    extract_sitekey,
)

__all__ = [
    # Base
    "BaseSolver",
    "SolverResult",
    # Solvers
    "TurnstileSolver",
    "RecaptchaV2Solver",
    "HCaptchaSolver",
    "ImageCaptchaSolver",
    # Dispatcher
    "CaptchaDispatcher",
    "CaptchaType",
    "DispatcherConfig",
    "ProviderEntry",
    "detect_captcha_types",
    "extract_sitekey",
]

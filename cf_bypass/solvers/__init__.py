"""Solver abstraction for Cloudflare Turnstile and captcha challenges.

Provides a pluggable architecture for captcha-solving services
(2captcha, Capsolver, Anti-Captcha) and browser-level token injection.
"""

from cf_bypass.solvers.base import BaseSolver, SolverResult
from cf_bypass.solvers.turnstile import TurnstileSolver

__all__ = ["BaseSolver", "SolverResult", "TurnstileSolver"]

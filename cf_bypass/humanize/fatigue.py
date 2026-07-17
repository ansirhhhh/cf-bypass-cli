"""Fatigue simulation for long-running sessions.

Over extended periods, human behavior degrades predictably:
- Typing slows down
- Mouse movements become less precise
- More typos and corrections
- Longer pauses between actions

This module implements a configurable fatigue curve that modulates
behavior parameters over session duration.
"""

import time
import random
from dataclasses import dataclass
from typing import Optional


@dataclass
class FatigueConfig:
    """Fatigue model parameters.

    Attributes:
        onset_minutes: Minutes before fatigue starts to affect behavior.
        full_effect_minutes: Minutes until fatigue reaches maximum effect.
        max_speed_penalty: Maximum multiplier on typing/mouse speed (>1 = slower).
        max_typo_increase: Maximum multiplier on typo probability.
        max_jitter_increase: Maximum multiplier on mouse jitter.
        recovery_break_prob: Probability per minute of a "micro-break" (50-200s).
    """

    onset_minutes: float = 15.0
    full_effect_minutes: float = 120.0
    max_speed_penalty: float = 1.8
    max_typo_increase: float = 3.0
    max_jitter_increase: float = 2.0
    recovery_break_prob: float = 0.05


class FatigueModel:
    """Track session duration and output fatigue multipliers.

    Usage::

        fatigue = FatigueModel()
        # ... 30 minutes of automation later ...
        speed_mult = fatigue.speed_multiplier()
        # -> 1.3 (30% slower typing/mouse)
        typo_mult = fatigue.typo_multiplier()
        # -> 1.8 (80% more typos)

        # Use in keyboard rhythm:
        adjusted_mean = base_mean * speed_mult
    """

    def __init__(self, config: Optional[FatigueConfig] = None):
        self.config = config or FatigueConfig()
        self._start_time = time.time()
        self._last_break: Optional[float] = None
        self._total_active_minutes = 0.0

    # ------------------------------------------------------------------
    # Fatigue multipliers
    # ------------------------------------------------------------------

    def elapsed_minutes(self) -> float:
        """Return elapsed session time in minutes."""
        return (time.time() - self._start_time) / 60.0

    def fatigue_level(self) -> float:
        """Return current fatigue level (0.0 = fresh, 1.0 = fully fatigued).

        Linear ramp from onset_minutes to full_effect_minutes.
        """
        cfg = self.config
        elapsed = self.elapsed_minutes()

        if elapsed < cfg.onset_minutes:
            return 0.0
        if elapsed >= cfg.full_effect_minutes:
            return 1.0

        return (elapsed - cfg.onset_minutes) / (
            cfg.full_effect_minutes - cfg.onset_minutes
        )

    def speed_multiplier(self) -> float:
        """Return typing/mouse speed multiplier (>1 = slower).

        At fatigue=0, returns 1.0 (normal speed).
        At fatigue=1, returns max_speed_penalty.
        """
        level = self.fatigue_level()
        return 1.0 + (self.config.max_speed_penalty - 1.0) * level

    def typo_multiplier(self) -> float:
        """Return typo probability multiplier.

        At fatigue=0, returns 1.0 (base typo rate).
        At fatigue=1, returns max_typo_increase.
        """
        level = self.fatigue_level()
        return 1.0 + (self.config.max_typo_increase - 1.0) * level

    def jitter_multiplier(self) -> float:
        """Return mouse jitter multiplier.

        At fatigue=0, returns 1.0 (base jitter).
        At fatigue=1, returns max_jitter_increase.
        """
        level = self.fatigue_level()
        return 1.0 + (self.config.max_jitter_increase - 1.0) * level

    def typing_delay(self, base_ms: float) -> float:
        """Apply fatigue to a base typing delay. Returns adjusted ms."""
        return base_ms * self.speed_multiplier()

    def mouse_speed_px_s(self, base_px_s: float) -> float:
        """Apply fatigue to a base mouse speed. Returns adjusted px/s."""
        return base_px_s / self.speed_multiplier()

    def should_take_break(self) -> bool:
        """Return True if a micro-break should happen right now.

        Call this once per action (~every few seconds).
        Probability increases with fatigue.
        """
        base_prob = self.config.recovery_break_prob
        fatigue_adj = base_prob * (1.0 + self.fatigue_level())

        if random.random() < fatigue_adj:
            self._last_break = time.time()
            return True
        return False

    def micro_break_duration_seconds(self) -> float:
        """Return a natural micro-break duration (50-200s).

        Longer breaks as fatigue increases.
        """
        base = random.uniform(50, 200)
        fatigue_bonus = self.fatigue_level() * random.uniform(30, 120)
        return base + fatigue_bonus

    # ------------------------------------------------------------------
    # Reset / tracking
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Reset fatigue (e.g. new user session)."""
        self._start_time = time.time()
        self._last_break = None

    def add_active_minutes(self, minutes: float) -> None:
        """Manually advance the fatigue clock (for testing)."""
        self._total_active_minutes += minutes

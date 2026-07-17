"""Human behavior simulation engine (L5).

Provides realistic mouse movement, keyboard typing, scroll behavior,
and fatigue modeling to make automated browser sessions appear human.

Key components:
- trajectory: Bezier + minimum-jerk path generation
- mouse: Fitts' law mouse movement with micro-corrections
- keyboard: Typing rhythm with burst/error patterns
- scroll: Natural scrolling with pauses and acceleration
- fatigue: Long-session behavior degradation
- behavior_synth: Composite behavior orchestration
"""

from cf_bypass.humanize.trajectory import TrajectoryGenerator
from cf_bypass.humanize.mouse import MouseController
from cf_bypass.humanize.keyboard import TypingRhythm
from cf_bypass.humanize.scroll import ScrollBehavior
from cf_bypass.humanize.fatigue import FatigueModel
from cf_bypass.humanize.behavior_synth import BehaviorSynth

__all__ = [
    "TrajectoryGenerator",
    "MouseController",
    "TypingRhythm",
    "ScrollBehavior",
    "FatigueModel",
    "BehaviorSynth",
]

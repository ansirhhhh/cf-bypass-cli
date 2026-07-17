"""Bezier curve and minimum-jerk trajectory generation.

Implements two algorithms for human-like cursor paths:

1. **Cubic Bezier** — fast, configurable, used in most game/automation tools.
   Adds 1-2 control points that introduce natural overshoot/curvature.

2. **Minimum Jerk** — bio-mechanically optimal (smooth derivative of
   acceleration). Produces the most human-like paths but is more expensive.

Default: Bezier with randomized control points (good balance of speed/quality).
"""

import math
import random
from dataclasses import dataclass
from typing import List, Tuple, Literal, Optional


# Type alias for a 3D waypoint (x, y, t_ms)
Waypoint = Tuple[float, float, float]


@dataclass
class TrajectoryConfig:
    """Configuration for trajectory generation.

    Attributes:
        algorithm: "bezier" (fast) or "min_jerk" (biomechanical).
        speed_mean: Mean cursor speed in px/s (default 800).
        speed_std: Standard deviation of speed (adds natural variation).
        jitter_px: Micro-jitter amplitude in pixels.
        overshoot_prob: Probability of overshooting the target (0.0-1.0).
        overshoot_px: Maximum overshoot distance in pixels.
        micro_pause_prob: Probability of a micro-pause mid-trajectory.
        micro_pause_ms: Duration range for micro-pauses (min, max).
        corner_radius: Control point radius for Bezier curvature.
    """

    algorithm: Literal["bezier", "min_jerk"] = "bezier"
    speed_mean: float = 800.0
    speed_std: float = 200.0
    jitter_px: float = 1.5
    overshoot_prob: float = 0.15
    overshoot_px: float = 40.0
    micro_pause_prob: float = 0.2
    micro_pause_ms: Tuple[float, float] = (30.0, 100.0)
    corner_radius: float = 200.0


class TrajectoryGenerator:
    """Generate human-like 2D cursor trajectories.

    Usage::

        gen = TrajectoryGenerator(TrajectoryConfig())
        path = gen.generate((100, 200), (800, 400))
        # path is list of (x, y, t_ms) waypoints

        for x, y, t in path:
            await page.mouse.move(x, y)
    """

    def __init__(self, config: Optional[TrajectoryConfig] = None):
        self.config = config or TrajectoryConfig()

    def generate(
        self,
        start: Tuple[float, float],
        end: Tuple[float, float],
        steps: int = 0,
    ) -> List[Waypoint]:
        """Generate a trajectory from start to end.

        Args:
            start: (x, y) starting position.
            end: (x, y) target position.
            steps: Number of waypoints. 0 = auto-calculate from distance.

        Returns:
            List of (x, y, t_ms) waypoints including start and end.
        """
        distance = math.hypot(end[0] - start[0], end[1] - start[1])

        if steps <= 0:
            # Auto-calculate: ~1 waypoint per 2px of travel
            steps = max(5, int(distance / 2))

        if self.config.algorithm == "min_jerk":
            return self._min_jerk_path(start, end, steps)
        else:
            return self._bezier_path(start, end, steps)

    # ------------------------------------------------------------------
    # Cubic Bezier with random control points
    # ------------------------------------------------------------------

    def _bezier_path(
        self,
        start: Tuple[float, float],
        end: Tuple[float, float],
        steps: int,
    ) -> List[Waypoint]:
        """Generate a cubic Bezier trajectory with overshoot and jitter."""
        cfg = self.config
        sx, sy = start
        ex, ey = end

        # Generate 2 control points with random curvature
        dx = ex - sx
        dy = ey - sy
        distance = math.hypot(dx, dy)

        # Perpendicular direction for curvature
        px = -dy / (distance + 0.001)
        py = dx / (distance + 0.001)

        # Control point offset magnitude (randomized)
        cp_offset = random.uniform(0.3, 0.7) * min(cfg.corner_radius, distance * 0.5)

        # Randomize perpendicular direction
        sign1 = random.choice([-1, 1])
        sign2 = random.choice([-1, 1])

        cp1_x = sx + dx * 0.33 + px * cp_offset * sign1
        cp1_y = sy + dy * 0.33 + py * cp_offset * sign1
        cp2_x = sx + dx * 0.66 + px * cp_offset * sign2
        cp2_y = sy + dy * 0.66 + py * cp_offset * sign2

        # Overshoot: occasionally pass the endpoint
        overshoot = 0.0
        if random.random() < cfg.overshoot_prob:
            overshoot = random.uniform(0, cfg.overshoot_px)
            ex += (dx / (distance + 0.001)) * overshoot
            ey += (dy / (distance + 0.001)) * overshoot

        # Generate bezier points
        points: List[Tuple[float, float]] = []
        for i in range(steps + 1):
            t = i / steps
            # Cubic Bezier: B(t) = (1-t)³P0 + 3(1-t)²tP1 + 3(1-t)t²P2 + t³P3
            mt = 1 - t
            x = mt**3 * sx + 3 * mt**2 * t * cp1_x + 3 * mt * t**2 * cp2_x + t**3 * ex
            y = mt**3 * sy + 3 * mt**2 * t * cp1_y + 3 * mt * t**2 * cp2_y + t**3 * ey

            # Add micro-jitter
            if cfg.jitter_px > 0 and 0 < i < steps:
                x += random.uniform(-cfg.jitter_px, cfg.jitter_px)
                y += random.uniform(-cfg.jitter_px, cfg.jitter_px)

            points.append((x, y))

        # Apply Fitts' law timing: slow start, fast middle, slow end
        return self._apply_timing(points, overshoot > 0)

    # ------------------------------------------------------------------
    # Minimum Jerk trajectory (bio-mechanically optimal)
    # ------------------------------------------------------------------

    def _min_jerk_path(
        self,
        start: Tuple[float, float],
        end: Tuple[float, float],
        steps: int,
    ) -> List[Waypoint]:
        """Generate a minimum-jerk (smoothest possible) trajectory.

        Based on Flash & Hogan (1985): the human motor system minimizes
        the integral of squared jerk (3rd derivative of position).

        Closed form: x(t) = x0 + (x0 - xf) * (15τ⁴ - 6τ⁵ - 10τ³)
        where τ = t / T (normalized time, 0→1).
        """
        cfg = self.config
        sx, sy = start
        ex, ey = end

        distance = math.hypot(ex - sx, ey - sy)
        total_time = distance / max(random.gauss(cfg.speed_mean, cfg.speed_std), 100)

        points: List[Waypoint] = []
        for i in range(steps + 1):
            tau = i / steps  # normalized time 0→1
            # Minimum jerk position profile
            coeff = 10 * tau**3 - 15 * tau**4 + 6 * tau**5

            x = sx + (ex - sx) * coeff
            y = sy + (ey - sy) * coeff
            t_ms = tau * total_time * 1000

            # Add micro-jitter
            if cfg.jitter_px > 0 and 0 < i < steps:
                x += random.uniform(-cfg.jitter_px, cfg.jitter_px)
                y += random.uniform(-cfg.jitter_px, cfg.jitter_px)

            points.append((x, y, t_ms))

        return points

    # ------------------------------------------------------------------
    # Fitts' law timing
    # ------------------------------------------------------------------

    def _apply_timing(
        self,
        points: List[Tuple[float, float]],
        has_overshoot: bool = False,
    ) -> List[Waypoint]:
        """Apply Fitts' law timing profile to a set of spatial points.

        Fitts' law: movement time ∝ log₂(distance/width + 1).
        This manifests as: slow start, peak mid-path velocity, slow end.
        """
        cfg = self.config
        n = len(points)
        if n < 2:
            return [(points[0][0], points[0][1], 0.0)] if points else []

        # Speed profile: asymmetric bell curve
        # Peak speed at ~40% of the path (humans accelerate faster than decelerate)
        speed = random.gauss(cfg.speed_mean, cfg.speed_std)
        speed = max(speed, 200)

        waypoints: List[Waypoint] = []
        cumulative_time = 0.0

        # If overshooting, add a correction phase at the end
        correction_start = int(n * 0.85) if has_overshoot else n

        for i in range(n):
            if i == 0:
                waypoints.append((points[i][0], points[i][1], 0.0))
                continue

            # Distance between consecutive points
            px, py = points[i - 1]
            cx, cy = points[i]
            seg_dist = math.hypot(cx - px, cy - py)

            # Normalized position in path (0→1)
            norm_pos = i / (n - 1)

            # Fitts' law speed profile: slow at 0, peak at 0.4, slow at 1
            if norm_pos < 0.05:
                # Initial acceleration (0→50% of target speed)
                speed_factor = norm_pos / 0.05 * 0.5
            elif norm_pos < 0.4:
                # Accelerating to peak
                speed_factor = 0.5 + (norm_pos - 0.05) / 0.35 * 0.5
            elif norm_pos < 0.85:
                # Peak speed plateau
                speed_factor = 1.0
            else:
                # Deceleration (Fitts' law approach phase)
                remaining = (1.0 - norm_pos) / 0.15
                speed_factor = remaining

            # Overshoot correction: very fast motion
            if i >= correction_start:
                speed_factor = 1.5

            effective_speed = max(speed * speed_factor, 50.0)  # minimum 50 px/s
            dt_ms = (seg_dist / effective_speed) * 1000

            # Micro-pauses: occasional 30-100ms halt
            if random.random() < cfg.micro_pause_prob and 0.1 < norm_pos < 0.9:
                dt_ms += random.uniform(*cfg.micro_pause_ms)

            cumulative_time += dt_ms
            waypoints.append((cx, cy, cumulative_time))

        return waypoints

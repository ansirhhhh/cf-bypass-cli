"""Natural scrolling behavior simulation.

Models how humans scroll web pages:
- Variable scroll distance (not uniform)
- Pauses at section boundaries (headings, images)
- Acceleration/deceleration phases
- Occasional micro-scrollbacks (re-reading)
- Reading-time-based pauses after text-heavy sections
"""

import random
import math
from dataclasses import dataclass
from typing import List, Tuple, Optional


@dataclass
class ScrollConfig:
    """Scroll behavior parameters.

    Attributes:
        min_step: Minimum scroll distance per step in pixels.
        max_step: Maximum scroll distance per step.
        pause_at_headings: Probability of pausing at h1-h3 elements.
        pause_duration_ms: Range for pause durations (min, max).
        scrollback_prob: Probability of a small scroll-up after scrolling.
        scrollback_px: Range for scrollback distance.
        reading_time_per_px: ms of reading time per pixel of content height.
        acceleration_phase: Fraction of scroll that accelerates (0-1).
        deceleration_phase: Fraction of scroll that decelerates (0-1).
    """

    min_step: float = 50.0
    max_step: float = 400.0
    pause_at_headings: float = 0.3
    pause_duration_ms: Tuple[float, float] = (500.0, 3000.0)
    scrollback_prob: float = 0.08
    scrollback_px: Tuple[float, float] = (30.0, 150.0)
    reading_time_per_px: float = 0.5  # ms per px
    acceleration_phase: float = 0.15
    deceleration_phase: float = 0.2


class ScrollBehavior:
    """Generate human-like page scrolling sequences.

    Usage::

        scroll = ScrollBehavior(page)
        await scroll.scroll_down(800)  # scroll 800px naturally
        await scroll.scroll_to_bottom()  # scroll to page bottom
        await scroll.read_and_scroll(duration=30)  # read + scroll for 30s
    """

    def __init__(
        self,
        page,
        config: Optional[ScrollConfig] = None,
    ):
        self.page = page
        self.config = config or ScrollConfig()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def scroll_down(
        self,
        total_distance: float,
        duration_seconds: Optional[float] = None,
    ) -> None:
        """Scroll down by *total_distance* pixels in human-like steps.

        Args:
            total_distance: Total pixels to scroll.
            duration_seconds: Target duration. If None, auto-calculates.
        """
        cfg = self.config
        steps = self._generate_steps(total_distance)
        total_pause_ms = sum(
            random.uniform(*cfg.pause_duration_ms)
            for _ in range(len(steps) // 3)  # pause every ~3 steps
            if random.random() < 0.3
        )

        if duration_seconds:
            total_ms = duration_seconds * 1000
            scroll_ms = max(total_ms - total_pause_ms, len(steps) * 30)
        else:
            scroll_ms = total_distance * cfg.reading_time_per_px

        await self._execute_scroll_steps(steps, scroll_ms)

    async def scroll_to_bottom(self, max_duration: float = 60.0) -> None:
        """Scroll to the bottom of the current page."""
        try:
            page_height = await self.page.evaluate(
                "document.body.scrollHeight"
            )
            viewport_height = await self.page.evaluate("window.innerHeight")
            current_scroll = await self.page.evaluate("window.scrollY")

            remaining = page_height - current_scroll - viewport_height
            if remaining <= 0:
                return

            await self.scroll_down(remaining, max_duration)
        except Exception:
            pass

    async def read_and_scroll(self, duration: float = 30.0) -> None:
        """Simulate reading a page for *duration* seconds.

        Alternates between reading pauses and natural scroll-downs.
        Mimics a human skimming content.
        """
        import asyncio
        deadline = asyncio.get_event_loop().time() + duration

        while asyncio.get_event_loop().time() < deadline:
            # Read for a bit
            read_time = random.uniform(1.0, 5.0)
            await asyncio.sleep(read_time)

            # Scroll a bit
            scroll_amount = random.uniform(100, 600)
            await self.scroll_down(scroll_amount)

            # Occasional scroll-up (re-reading)
            if random.random() < self.config.scrollback_prob:
                back_amount = random.uniform(*self.config.scrollback_px)
                await self.scroll_up(back_amount)

    async def scroll_up(self, distance: float) -> None:
        """Scroll up (back) by *distance* pixels."""
        steps = int(max(1, distance / 80))
        step_size = distance / steps

        for i in range(steps):
            # Deceleration curve when scrolling back
            progress = (i + 1) / steps
            eased_step = step_size * (1 - progress * 0.5)

            await self._do_scroll(-eased_step)
            await self._sleep_ms(random.uniform(50, 150))

    async def scroll_to_element(self, selector: str) -> None:
        """Smooth-scroll to a specific element."""
        try:
            await self.page.evaluate(f"""
                document.querySelector('{selector}').scrollIntoView({{
                    behavior: 'smooth',
                    block: 'center',
                }});
            """)
            # Wait for smooth scroll to complete
            await self._sleep_ms(1000)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _generate_steps(self, total_distance: float) -> List[float]:
        """Generate a list of step distances with acceleration/deceleration."""
        cfg = self.config
        if total_distance <= 0:
            return []

        # Target ~ one step per 200-400px
        num_steps = max(3, int(total_distance / random.uniform(200, 400)))
        steps: List[float] = []

        for i in range(num_steps):
            progress = i / (num_steps - 1) if num_steps > 1 else 0.5

            # Step size follows acceleration → cruise → deceleration
            if progress < cfg.acceleration_phase:
                # Acceleration: steps get larger
                factor = progress / cfg.acceleration_phase
                step_size = cfg.min_step + (cfg.max_step - cfg.min_step) * factor * 0.5
            elif progress > (1 - cfg.deceleration_phase):
                # Deceleration: steps get smaller
                remaining = (1 - progress) / cfg.deceleration_phase
                step_size = cfg.min_step + (cfg.max_step - cfg.min_step) * remaining * 0.3
            else:
                # Cruise: random mid-range
                step_size = random.uniform(
                    cfg.min_step + (cfg.max_step - cfg.min_step) * 0.3,
                    cfg.max_step,
                )

            steps.append(step_size)

        # Normalize to match total_distance
        total = sum(steps)
        if total > 0:
            scale = total_distance / total
            steps = [s * scale for s in steps]

        return steps

    async def _execute_scroll_steps(
        self,
        steps: List[float],
        total_scroll_ms: float,
    ) -> None:
        """Execute scroll steps with natural timing."""
        cfg = self.config
        if not steps:
            return

        # Distribute time: 70% for scrolling, 30% for pauses
        scroll_time_per_step = (total_scroll_ms * 0.7) / len(steps)
        pause_count = 0

        for i, step in enumerate(steps):
            await self._do_scroll(step)
            await self._sleep_ms(scroll_time_per_step)

            # Random pauses
            if random.random() < 0.3:
                pause_ms = random.uniform(*cfg.pause_duration_ms)
                await self._sleep_ms(pause_ms)
                pause_count += 1

            # Scrollback
            if random.random() < cfg.scrollback_prob:
                back_px = random.uniform(*cfg.scrollback_px)
                await self._do_scroll(-back_px)
                await self._sleep_ms(random.uniform(100, 400))

    async def _do_scroll(self, delta_y: float) -> None:
        """Execute a single scroll action."""
        try:
            # Try Playwright API
            await self.page.mouse.wheel(0, delta_y)
        except Exception:
            try:
                # Fallback: JS window.scrollBy
                await self.page.evaluate(f"window.scrollBy(0, {delta_y})")
            except Exception:
                pass

    @staticmethod
    async def _sleep_ms(ms: float) -> None:
        import asyncio
        await asyncio.sleep(ms / 1000.0)

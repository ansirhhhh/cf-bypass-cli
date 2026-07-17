"""Human-like mouse movement controller.

Implements Fitts' law-compliant cursor movement with:
- Bezier or minimum-jerk trajectory
- Pre-move micro-wiggles (1-3s of jitter at current position)
- Post-move hover delay (200-500ms before click)
- Click with ±2px offset from element center
- Double-click with variable inter-click interval
"""

import random
import time
from typing import Optional, Tuple

from cf_bypass.humanize.trajectory import TrajectoryGenerator, TrajectoryConfig
from cf_bypass.logging_config import get_logger

logger = get_logger("humanize.mouse")


class MouseController:
    """Orchestrate human-like mouse interactions on a browser page.

    Usage::

        mouse = MouseController(page)
        await mouse.move_to("#login-button")
        await mouse.click()
        await mouse.move_to("#username")
        await mouse.type_with_keyboard("admin")  # delegates to keyboard module
    """

    def __init__(
        self,
        page,
        trajectory_config: Optional[TrajectoryConfig] = None,
        profile: str = "windows_chrome",
    ):
        """Initialize mouse controller.

        Args:
            page: Playwright or nodriver page object.
            trajectory_config: Trajectory generation parameters.
            profile: OS/browser profile ("windows_chrome", "macos_chrome", "linux_chrome").
        """
        self.page = page
        self.trajectory = TrajectoryGenerator(trajectory_config)
        self.profile = profile
        self._current_pos: Tuple[float, float] = (random.randint(100, 800), random.randint(100, 600))

    # ------------------------------------------------------------------
    # Movement
    # ------------------------------------------------------------------

    async def move_to(
        self,
        selector: str,
        offset: Tuple[int, int] = (0, 0),
        pre_wiggle: bool = True,
    ) -> None:
        """Move cursor to an element with human-like trajectory.

        Args:
            selector: CSS selector for the target element.
            offset: Pixel offset from element center (±2px noise added automatically).
            pre_wiggle: If True, add 1-3s of micro-jitter before starting the move.
        """
        try:
            # Get element bounding box
            box = await self._get_bounding_box(selector)
            if not box:
                logger.debug(f"Element '{selector}' not found for mouse move")
                return

            # Target: center + offset + ±2px natural noise
            target_x = box["x"] + box["width"] / 2 + offset[0] + random.uniform(-2, 2)
            target_y = box["y"] + box["height"] / 2 + offset[1] + random.uniform(-2, 2)

            # Pre-move wiggle at current position
            if pre_wiggle:
                await self._pre_move_wiggle()

            # Generate trajectory
            start = self._current_pos
            end = (target_x, target_y)
            path = self.trajectory.generate(start, end)

            # Execute movement
            logger.debug(
                f"Mouse move: ({start[0]:.0f},{start[1]:.0f}) → "
                f"({end[0]:.0f},{end[1]:.0f}) in {len(path)} steps"
            )

            for x, y, t_ms in path:
                await self._move_to(x, y)
                # Sleep to match the timing profile
                if t_ms > 0:
                    await self._sleep_ms(min(t_ms - getattr(self, '_last_t', 0), 50))
                    object.__setattr__(self, '_last_t', t_ms)

            self._current_pos = end

            # Post-move hover (200-500ms) — humans pause to read
            hover_ms = random.uniform(200, 500)
            await self._sleep_ms(hover_ms)

        except Exception as exc:
            logger.debug(f"Mouse move failed: {exc}")

    async def move_to_coords(
        self,
        x: float,
        y: float,
        pre_wiggle: bool = False,
    ) -> None:
        """Move cursor to absolute coordinates."""
        start = self._current_pos
        end = (x + random.uniform(-2, 2), y + random.uniform(-2, 2))

        if pre_wiggle:
            await self._pre_move_wiggle()

        path = self.trajectory.generate(start, end)
        for px, py, t_ms in path:
            await self._move_to(px, py)

        self._current_pos = end
        await self._sleep_ms(random.uniform(100, 300))

    # ------------------------------------------------------------------
    # Click actions
    # ------------------------------------------------------------------

    async def click(
        self,
        selector: Optional[str] = None,
        button: str = "left",
        click_count: int = 1,
    ) -> None:
        """Click at current position or on a selector.

        Args:
            selector: If provided, move to this element first.
            button: "left", "right", or "middle".
            click_count: 1 for single, 2 for double-click.
        """
        if selector:
            await self.move_to(selector)

        try:
            if click_count == 2:
                # Double-click with human-like inter-click interval
                interval = random.uniform(80, 200)  # ms
                await self._click(self._current_pos[0], self._current_pos[1], button)
                await self._sleep_ms(interval)
                await self._click(self._current_pos[0], self._current_pos[1], button)
                logger.debug("Double-click executed")
            else:
                await self._click(self._current_pos[0], self._current_pos[1], button)
                logger.debug(f"{button} click at ({self._current_pos[0]:.0f},{self._current_pos[1]:.0f})")
        except Exception as exc:
            logger.debug(f"Click failed: {exc}")

    async def right_click(self, selector: Optional[str] = None) -> None:
        """Right-click at current position or on selector."""
        await self.click(selector, button="right")

    async def double_click(self, selector: Optional[str] = None) -> None:
        """Double-click at current position or on selector."""
        await self.click(selector, click_count=2)

    # ------------------------------------------------------------------
    # Drag and drop
    # ------------------------------------------------------------------

    async def drag_to(
        self,
        target_selector: str,
        source_selector: Optional[str] = None,
    ) -> None:
        """Drag from current position (or source selector) to target.

        Mouse down → move with trajectory → mouse up.
        """
        if source_selector:
            await self.move_to(source_selector)

        start = self._current_pos

        # Get target position
        box = await self._get_bounding_box(target_selector)
        if not box:
            return

        end = (
            box["x"] + box["width"] / 2 + random.uniform(-2, 2),
            box["y"] + box["height"] / 2 + random.uniform(-2, 2),
        )

        try:
            await self._mouse_down()
            path = self.trajectory.generate(start, end)
            for x, y, _ in path:
                await self._move_to(x, y)
                await self._sleep_ms(10)  # drag is slower than normal move
            await self._mouse_up()
            self._current_pos = end
            logger.debug(f"Drag: ({start[0]:.0f},{start[1]:.0f}) → ({end[0]:.0f},{end[1]:.0f})")
        except Exception as exc:
            logger.debug(f"Drag failed: {exc}")

    # ------------------------------------------------------------------
    # Scroll wheel
    # ------------------------------------------------------------------

    async def scroll(
        self,
        delta_y: int,
        delta_x: int = 0,
        steps: int = 0,
    ) -> None:
        """Perform a human-like scroll with multiple small steps.

        Args:
            delta_y: Total vertical scroll amount in pixels.
            delta_x: Horizontal scroll amount.
            steps: Number of sub-steps. 0 = auto-calculate.
        """
        if steps <= 0:
            steps = max(3, abs(delta_y) // 50)

        step_y = delta_y / steps
        step_x = delta_x / steps if delta_x else 0

        for i in range(steps):
            await self._mouse_wheel(step_x, step_y)
            # Variable delay between scroll steps (simulates reading)
            await self._sleep_ms(random.uniform(30, 120))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _pre_move_wiggle(self) -> None:
        """Add 1-3 seconds of micro-jitter at current position."""
        wiggle_duration = random.uniform(1.0, 3.0)
        wiggle_steps = int(wiggle_duration * 10)  # ~10Hz
        cx, cy = self._current_pos

        for _ in range(wiggle_steps):
            jx = cx + random.uniform(-3, 3)
            jy = cy + random.uniform(-3, 3)
            try:
                await self._move_to(jx, jy)
                await self._sleep_ms(random.uniform(80, 120))
            except Exception:
                break

    async def _get_bounding_box(self, selector: str) -> Optional[dict]:
        """Get element bounding box from a page.

        Works with both Playwright (locator.bounding_box) and nodriver (evaluate).
        """
        try:
            # Playwright-style
            locator = self.page.locator(selector)
            box = await locator.bounding_box()
            if box:
                return box
        except Exception:
            pass

        try:
            # nodriver-style: use JS evaluate
            result = await self.page.evaluate(f"""
                (() => {{
                    const el = document.querySelector('{selector}');
                    if (!el) return null;
                    const rect = el.getBoundingClientRect();
                    return {{ x: rect.x, y: rect.y, width: rect.width, height: rect.height }};
                }})()
            """)
            if result:
                return result
        except Exception:
            pass

        return None

    async def _move_to(self, x: float, y: float) -> None:
        """Move mouse to absolute coordinates (browser-agnostic)."""
        # Try Playwright API
        try:
            await self.page.mouse.move(x, y)
            return
        except Exception:
            pass

        # Try nodriver CDP
        try:
            await self.page.evaluate(f"""
                document.elementFromPoint({x}, {y});
            """)
            # nodriver doesn't have mouse.move directly; use CDP
            cdp = await self.page.browser.cdp()
            await cdp.send("Input.dispatchMouseEvent", {
                "type": "mouseMoved",
                "x": x,
                "y": y,
            })
        except Exception:
            pass  # best effort

    async def _click(self, x: float, y: float, button: str = "left") -> None:
        """Click at coordinates."""
        try:
            await self.page.mouse.click(x, y, button=button)
        except Exception:
            try:
                cdp = await self.page.browser.cdp()
                await cdp.send("Input.dispatchMouseEvent", {
                    "type": "mousePressed",
                    "x": x, "y": y,
                    "button": button,
                    "clickCount": 1,
                })
                await cdp.send("Input.dispatchMouseEvent", {
                    "type": "mouseReleased",
                    "x": x, "y": y,
                    "button": button,
                    "clickCount": 1,
                })
            except Exception:
                pass

    async def _mouse_down(self) -> None:
        try:
            await self.page.mouse.down()
        except Exception:
            pass

    async def _mouse_up(self) -> None:
        try:
            await self.page.mouse.up()
        except Exception:
            pass

    async def _mouse_wheel(self, dx: float, dy: float) -> None:
        try:
            await self.page.mouse.wheel(dx, dy)
        except Exception:
            pass

    @staticmethod
    async def _sleep_ms(ms: float) -> None:
        import asyncio
        await asyncio.sleep(ms / 1000.0)

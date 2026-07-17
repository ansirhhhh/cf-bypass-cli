"""Composite behavior synthesis.

Orchestrates multiple humanize modules to produce realistic browsing
sessions. This is the main integration point for L3/L4 strategies.

Key scenarios:
1. **Warm-up** — visit neutral sites before the target (5-15s)
2. **Page interaction** — scroll, hover, read after landing
3. **Form filling** — type into inputs with natural rhythm
4. **Pre-navigation** — pre-move wiggle before navigating
"""

import random
import asyncio
from typing import Optional, List

from cf_bypass.humanize.mouse import MouseController
from cf_bypass.humanize.keyboard import TypingRhythm
from cf_bypass.humanize.scroll import ScrollBehavior
from cf_bypass.humanize.fatigue import FatigueModel
from cf_bypass.logging_config import get_logger

logger = get_logger("humanize.behavior_synth")

# Common neutral/referrer sites for warm-up
DEFAULT_WARMUP_SITES = [
    "https://news.ycombinator.com",
    "https://www.bbc.com/news",
    "https://www.reddit.com",
    "https://en.wikipedia.org/wiki/Main_Page",
    "https://www.bing.com",
]


class BehaviorSynth:
    """Orchestrate human-like browsing behavior.

    Usage::

        synth = BehaviorSynth(page)
        await synth.warm_up(target_domain="example.com")
        await synth.interact_with_page(depth=2)
        await synth.fill_input("#search", "hello world")
    """

    def __init__(
        self,
        page,
        mouse_profile: str = "windows_chrome",
        typing_profile: str = "casual",
    ):
        """Initialize behavior synthesizer for a browser page.

        Args:
            page: Playwright or nodriver page object.
            mouse_profile: "windows_chrome", "macos_chrome", "linux_chrome".
            typing_profile: "casual", "professional", "tired", "hunt_and_peck".
        """
        self.page = page
        self.mouse = MouseController(page, profile=mouse_profile)
        self.keyboard = TypingRhythm(profile=typing_profile)
        self.scroll = ScrollBehavior(page)
        self.fatigue = FatigueModel()

    # ------------------------------------------------------------------
    # Warm-up: browse neutral sites before target
    # ------------------------------------------------------------------

    async def warm_up(
        self,
        target_domain: str = "",
        sites: Optional[List[str]] = None,
        min_duration: float = 5.0,
        max_duration: float = 15.0,
    ) -> None:
        """Visit 1-2 neutral sites before navigating to the target.

        This mimics a human who was browsing the web before arriving
        at the target site. The referrer chain looks natural.

        Args:
            target_domain: The ultimate destination (not visited here).
            sites: Custom warm-up sites. Uses DEFAULT_WARMUP_SITES if None.
            min_duration: Minimum time to spend on warm-up sites.
            max_duration: Maximum time to spend on warm-up sites.
        """
        sites = sites or DEFAULT_WARMUP_SITES
        num_sites = random.randint(1, min(2, len(sites)))
        chosen = random.sample(sites, num_sites)

        target_duration = random.uniform(min_duration, max_duration)
        per_site = target_duration / num_sites

        logger.debug(f"Behavior warm-up: {num_sites} site(s), ~{target_duration:.0f}s")

        for site in chosen:
            try:
                # Navigate to warm-up site
                if hasattr(self.page, "goto"):
                    await self.page.goto(site, wait_until="domcontentloaded", timeout=15000)
                elif hasattr(self.page, "get"):
                    await self.page.get(site)

                await self._sleep(1.0)

                # Simulate reading: scroll a bit, move mouse
                await self.scroll.scroll_down(random.uniform(200, 800))
                await self.mouse.move_to_coords(
                    random.uniform(200, 800),
                    random.uniform(200, 500),
                )

                # Spend remaining time
                remaining = per_site - 1.0
                if remaining > 0:
                    await self.scroll.read_and_scroll(duration=remaining)

            except Exception as exc:
                logger.debug(f"Warm-up site {site} failed (non-fatal): {exc}")

    # ------------------------------------------------------------------
    # Page interaction: read, scroll, hover
    # ------------------------------------------------------------------

    async def interact_with_page(self, depth: int = 2) -> None:
        """Simulate a human reading/interacting with the current page.

        Args:
            depth: Interaction depth (1=light, 3=engaged).
                - 1: Quick scan (2-5s)
                - 2: Normal reading (5-15s)
                - 3: Deep engagement (15-30s)
        """
        duration = {1: (2.0, 5.0), 2: (5.0, 15.0), 3: (15.0, 30.0)}.get(
            depth, (5.0, 15.0)
        )
        target_duration = random.uniform(*duration)

        logger.debug(f"Page interaction: depth={depth}, ~{target_duration:.0f}s")

        # Read/scroll
        await self.scroll.read_and_scroll(duration=target_duration * 0.6)

        # Hover over random elements
        await self._hover_random_elements(count=min(depth, 3))

        # More scrolling
        await self.scroll.read_and_scroll(duration=target_duration * 0.4)

    async def _hover_random_elements(self, count: int = 2) -> None:
        """Hover over random visible elements (links, buttons, images)."""
        hover_selectors = [
            "a[href]:not([href='#'])",
            "button:not([disabled])",
            "img[src]",
            "h1, h2, h3",
            "p",
        ]

        for _ in range(count):
            selector = random.choice(hover_selectors)
            try:
                await self.mouse.move_to(selector, pre_wiggle=False)
                # Brief hover
                await self._sleep(random.uniform(0.3, 1.5))
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Form filling: type into inputs naturally
    # ------------------------------------------------------------------

    async def fill_input(
        self,
        selector: str,
        text: str,
        click_first: bool = True,
    ) -> None:
        """Type text into a form input with human rhythm.

        Args:
            selector: CSS selector for the input element.
            text: Text to type.
            click_first: If True, click the element before typing (focuses it).
        """
        # Move to the input
        await self.mouse.move_to(selector)

        if click_first:
            await self.mouse.click()
            await self._sleep(random.uniform(0.2, 0.5))

        # Type with rhythm
        intervals = self.keyboard.intervals(text)

        try:
            for char, delay in zip(text, intervals):
                await self._press_key(char)
                await self._sleep(delay / 1000.0)
        except Exception as exc:
            logger.debug(f"Typing failed for '{selector}': {exc}")

    async def fill_form(
        self,
        fields: List[tuple],
    ) -> None:
        """Fill multiple form fields in sequence.

        Args:
            fields: List of (selector, text, tab_after) tuples.
                    tab_after: if True, press Tab after typing (default True).
        """
        for i, field in enumerate(fields):
            selector = field[0]
            text = field[1]
            tab_after = field[2] if len(field) > 2 else True

            await self.fill_input(selector, text)

            if tab_after and i < len(fields) - 1:
                await self._press_key("Tab")
                await self._sleep(random.uniform(0.3, 0.8))

    # ------------------------------------------------------------------
    # Pre-navigation behavior
    # ------------------------------------------------------------------

    async def pre_navigate(self) -> None:
        """Execute before navigating to a new URL.

        Humans don't teleport between pages — they look at something,
        maybe scroll to the bottom, then click a link or type a URL.
        """
        # Quick glance at current page
        await self._sleep(random.uniform(0.5, 2.0))

        # Micro wiggle
        await self.mouse.move_to_coords(
            random.uniform(200, 1000),
            random.uniform(200, 700),
            pre_wiggle=True,
        )

    async def post_navigate(self) -> None:
        """Execute after a new page loads.

        Humans take a moment to orient after a page loads.
        """
        # Orientation pause
        await self._sleep(random.uniform(1.0, 3.0))

        # Initial micro-scroll (humans rarely sit perfectly still)
        await self.scroll.scroll_down(random.uniform(0, 200))

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    async def _press_key(self, key: str) -> None:
        """Press a keyboard key (browser-agnostic)."""
        try:
            await self.page.keyboard.press(key)
        except Exception:
            try:
                await self.page.keyboard.type(key)
            except Exception:
                pass

    @staticmethod
    async def _sleep(seconds: float) -> None:
        await asyncio.sleep(seconds)

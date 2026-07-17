"""Human-like keyboard typing rhythm generator.

Models natural typing patterns:
- Variable inter-key delays (Gaussian distribution per profile)
- Common bigram acceleration ("th", "er", "in", etc.)
- Punctuation/capitalization pauses (200-400ms)
- Occasional bursts of 3-5 fast keys (muscle memory)
- 1-2% chance of typo + backspace correction
"""

import random
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional

# Common English bigrams that are typed faster (muscle memory)
FAST_BIGRAMS: Dict[str, float] = {
    "th": 0.7, "he": 0.7, "in": 0.7, "er": 0.7, "an": 0.7,
    "re": 0.75, "on": 0.75, "at": 0.75, "en": 0.75, "nd": 0.75,
    "ti": 0.8, "es": 0.8, "or": 0.8, "te": 0.8, "of": 0.8,
    "ed": 0.8, "is": 0.8, "it": 0.8, "al": 0.8, "ar": 0.8,
    "st": 0.8, "to": 0.8, "nt": 0.8, "ng": 0.85, "se": 0.85,
    "ha": 0.85, "as": 0.85, "ou": 0.85, "io": 0.85, "le": 0.85,
}

# Common single-key typos (adjacent keys on QWERTY)
ADJACENT_KEYS: Dict[str, List[str]] = {
    "a": ["q", "w", "s", "z"], "b": ["v", "g", "h", "n"],
    "c": ["x", "d", "f", "v"], "d": ["s", "e", "r", "f", "c", "x"],
    "e": ["w", "s", "d", "r"], "f": ["d", "r", "t", "g", "v", "c"],
    "g": ["f", "t", "y", "h", "b", "v"], "h": ["g", "y", "u", "j", "n", "b"],
    "i": ["u", "j", "k", "o"], "j": ["h", "u", "i", "k", "m", "n"],
    "k": ["j", "i", "o", "l", "m"], "l": ["k", "o", "p"],
    "m": ["n", "j", "k"], "n": ["b", "h", "j", "m"],
    "o": ["i", "k", "l", "p"], "p": ["o", "l"],
    "q": ["a", "w"], "r": ["e", "d", "f", "t"],
    "s": ["a", "w", "e", "d", "x", "z"], "t": ["r", "f", "g", "y"],
    "u": ["y", "h", "j", "i"], "v": ["c", "f", "g", "b"],
    "w": ["q", "a", "s", "e"], "x": ["z", "s", "d", "c"],
    "y": ["t", "g", "h", "u"], "z": ["a", "s", "x"],
}


@dataclass
class TypingProfile:
    """Typing speed and rhythm parameters.

    Attributes:
        mean: Mean inter-key delay in ms.
        std: Standard deviation of inter-key delay.
        burst_prob: Probability of a 3-5 key fast burst.
        burst_speed: Speed multiplier during a burst (lower = faster).
        typo_prob: Per-character probability of a typo.
        caps_penalty_ms: Extra delay before pressing a capital letter.
        punctuation_penalty_ms: Extra delay before punctuation.
        space_jitter_ms: Extra jitter on spacebar timing.
    """

    mean: float = 180.0
    std: float = 60.0
    burst_prob: float = 0.05
    burst_speed: float = 0.5
    typo_prob: float = 0.015
    caps_penalty_ms: float = 150.0
    punctuation_penalty_ms: float = 250.0
    space_jitter_ms: float = 40.0


# Pre-built profiles
TYPING_PROFILES = {
    "casual": TypingProfile(
        mean=200, std=70, burst_prob=0.05,
        typo_prob=0.02,
    ),
    "professional": TypingProfile(
        mean=110, std=35, burst_prob=0.02,
        typo_prob=0.008,
    ),
    "tired": TypingProfile(
        mean=280, std=120, burst_prob=0.10,
        typo_prob=0.03,
    ),
    "hunt_and_peck": TypingProfile(
        mean=400, std=150, burst_prob=0.0,
        typo_prob=0.05, burst_speed=0.8,
    ),
}


class TypingRhythm:
    """Generate realistic inter-key intervals for a given text.

    Usage::

        rhythm = TypingRhythm("professional")
        intervals = rhythm.intervals("Hello, world!")
        # intervals = [120, 145, 108, 380, 210, ...]

        for char, delay in zip(text, intervals):
            await page.keyboard.press(char)
            await asyncio.sleep(delay / 1000)
    """

    def __init__(
        self,
        profile: str = "casual",
        custom_profile: Optional[TypingProfile] = None,
    ):
        """Initialize with a named profile or custom TypingProfile.

        Args:
            profile: One of "casual", "professional", "tired", "hunt_and_peck".
            custom_profile: Override with a custom TypingProfile.
        """
        self.profile = custom_profile or TYPING_PROFILES.get(
            profile, TYPING_PROFILES["casual"]
        )

    def intervals(self, text: str) -> List[float]:
        """Generate inter-key delay intervals for *text*.

        Returns a list of ms delays, one per character position.
        The first character has delay 0 (no preceding key).
        The last delay is the time AFTER the last keypress.

        Includes:
        - Gaussian variation around profile.mean
        - Faster bigrams
        - Punctuation delays
        - Caps key delay
        - Occasional burst sequences
        - Typos + backspace corrections (embedded as extra entries)
        """
        if not text:
            return []

        pf = self.profile
        delays: List[float] = []

        i = 0
        burst_remaining = 0

        while i < len(text):
            if i == 0:
                delays.append(0.0)
                i += 1
                continue

            prev_char = text[i - 1].lower() if i > 0 else ""
            curr_char = text[i].lower()

            # Check for burst mode
            if burst_remaining > 0:
                delay = random.gauss(pf.mean * pf.burst_speed, pf.std * 0.5)
                burst_remaining -= 1
            elif random.random() < pf.burst_prob:
                burst_remaining = random.randint(2, 4)
                delay = random.gauss(pf.mean * pf.burst_speed, pf.std * 0.5)
            else:
                delay = random.gauss(pf.mean, pf.std)

            # Ensure positive
            delay = max(delay, 20)

            # Bigram acceleration
            bigram = prev_char + curr_char
            if bigram in FAST_BIGRAMS:
                delay *= FAST_BIGRAMS[bigram]

            # Capital letter penalty (previous keystroke was Shift or Caps)
            if i > 0 and text[i - 1].isupper() and text[i - 1].isalpha():
                delay += random.uniform(0, pf.caps_penalty_ms)

            # Punctuation penalty (for the character BEFORE punctuation)
            if curr_char in ",.!?;:-":
                delay += random.uniform(0, pf.punctuation_penalty_ms)

            # Space bar jitter
            if curr_char == " ":
                delay += random.uniform(-pf.space_jitter_ms, pf.space_jitter_ms)

            # Typo + correction
            if curr_char.isalpha() and random.random() < pf.typo_prob:
                typo_char = self._adjacent_key(curr_char)
                if typo_char:
                    # Insert: [typo delay, backspace delay, correct delay]
                    typo_delay = random.gauss(pf.mean, pf.std)
                    backspace_delay = random.gauss(pf.mean * 1.2, pf.std * 0.5)
                    correct_delay = random.gauss(pf.mean * 1.1, pf.std)

                    delays.append(max(typo_delay, 20))
                    delays.append(max(backspace_delay, 30))
                    delays.append(max(correct_delay, 20))
                    i += 1
                    continue

            delays.append(delay)
            i += 1

        return delays

    def generate_key_events(self, text: str) -> List[Tuple[str, float, str]]:
        """Generate (char, delay_ms, action) tuples for typing *text*.

        Returns a list where each entry is:
            (character, delay_before_ms, action)
        Actions: "press", "backspace", "shift_press"

        This is useful for direct keyboard simulation.
        """
        if not text:
            return []

        pf = self.profile
        intervals = self.intervals(text)
        events: List[Tuple[str, float, str]] = []

        # We need to handle typos by splitting the intervals back into
        # individual key events. Simpler approach: regenerate.
        burst_remaining = 0
        delays: List[float] = []

        for i, char in enumerate(text):
            if i == 0:
                delays.append(0.0)
                continue

            prev_char = text[i - 1].lower() if i > 0 else ""
            curr_char = char.lower()

            if burst_remaining > 0:
                delay = random.gauss(pf.mean * pf.burst_speed, pf.std * 0.5)
                burst_remaining -= 1
            elif random.random() < pf.burst_prob:
                burst_remaining = random.randint(2, 4)
                delay = random.gauss(pf.mean * pf.burst_speed, pf.std * 0.5)
            else:
                delay = random.gauss(pf.mean, pf.std)

            delay = max(delay, 20)

            bigram = prev_char + curr_char
            if bigram in FAST_BIGRAMS:
                delay *= FAST_BIGRAMS[bigram]

            if curr_char in ",.!?;:-":
                delay += random.uniform(0, pf.punctuation_penalty_ms)
            if curr_char == " ":
                delay += random.uniform(-pf.space_jitter_ms, pf.space_jitter_ms)

            delays.append(delay)

        for i, char in enumerate(text):
            action = "press"
            delay = delays[i]
            events.append((char, delay, action))

        return events

    @staticmethod
    def _adjacent_key(char: str) -> Optional[str]:
        """Return a random adjacent key on QWERTY, or None."""
        adjacent = ADJACENT_KEYS.get(char.lower())
        if adjacent:
            result = random.choice(adjacent)
            return result.upper() if char.isupper() else result
        return None

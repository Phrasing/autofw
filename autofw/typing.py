import asyncio
import random
from dataclasses import dataclass

from autofw.delays import SPEED_PROFILES


@dataclass(frozen=True)
class TypingConfig:
    speed: str = "normal"
    punctuation_chars: str = ".,@!?-_"
    punctuation_delay: tuple[float, float] = (0.05, 0.15)
    pause_probability: float = 0.03
    pause_duration: tuple[float, float] = (0.2, 0.5)
    acceleration_threshold: int = 3
    acceleration_probability: float = 0.3
    acceleration_factor: float = 0.85


async def human_type(
    element,
    text: str,
    config: TypingConfig | None = None,
    speed_multiplier: float = 1.0,
) -> None:
    """Type text character-by-character with human-like delays."""
    cfg = config or TypingConfig()
    base_min, base_max = SPEED_PROFILES.get(cfg.speed, SPEED_PROFILES["normal"])

    for i, char in enumerate(text):
        await element.send_keys(char)
        delay = random.uniform(base_min, base_max)

        if char in cfg.punctuation_chars:
            delay += random.uniform(*cfg.punctuation_delay)

        if random.random() < cfg.pause_probability:
            delay += random.uniform(*cfg.pause_duration)

        if i > cfg.acceleration_threshold and random.random() < cfg.acceleration_probability:
            delay *= cfg.acceleration_factor

        await asyncio.sleep(delay / speed_multiplier)

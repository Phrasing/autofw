import asyncio
import random
from dataclasses import dataclass, field

DELAYS: dict[str, tuple[float, float]] = {
    "micro": (0.05, 0.15),
    "short": (0.3, 0.8),
    "action": (0.8, 2.0),
    "thinking": (1.5, 3.5),
    "page": (2.5, 4.5),
}

SPEED_PROFILES: dict[str, tuple[float, float]] = {
    "fast": (0.03, 0.08),
    "normal": (0.05, 0.12),
    "slow": (0.08, 0.18),
}


@dataclass(frozen=True)
class DelayProfile:
    delays: dict[str, tuple[float, float]] = field(default_factory=lambda: dict(DELAYS))
    speed_multiplier: float = 1.0
    extra_delay_probability: float = 0.1
    extra_delay_range: tuple[float, float] = (0.5, 1.5)


async def random_delay(mode: str = "action", profile: DelayProfile | None = None) -> None:
    """Wait for a random duration based on delay mode."""
    p = profile or DelayProfile()
    min_d, max_d = p.delays.get(mode, DELAYS["action"])

    if mode != "micro" and random.random() < p.extra_delay_probability:
        max_d += random.uniform(*p.extra_delay_range)

    await asyncio.sleep(random.uniform(min_d, max_d) / p.speed_multiplier)

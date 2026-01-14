import asyncio
from dataclasses import dataclass
from typing import Awaitable, Callable, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class RetryConfig:
    max_retries: int = 3
    base_delay: float = 1.0
    max_delay: float = 10.0
    exponential: bool = True


async def retry(
    operation: Callable[[], Awaitable[T]],
    config: RetryConfig | None = None,
    description: str = "operation",
    on_retry: Callable[[int, int, Exception], None] | None = None,
) -> T:
    """Execute an async operation with retry logic and exponential backoff."""
    cfg = config or RetryConfig()
    last_error: Exception | None = None

    for attempt in range(cfg.max_retries + 1):
        try:
            return await operation()
        except Exception as e:
            last_error = e
            if attempt < cfg.max_retries:
                delay = min(cfg.base_delay * (2**attempt), cfg.max_delay) if cfg.exponential else cfg.base_delay
                if on_retry:
                    on_retry(attempt + 1, cfg.max_retries, e)
                await asyncio.sleep(delay)

    raise last_error  # type: ignore[misc]

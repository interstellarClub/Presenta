import asyncio
import random


class RetryableUpstreamError(Exception):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def is_retryable_status(status_code: int) -> bool:
    return status_code == 429 or 500 <= status_code < 600


async def sleep_backoff(attempt: int, base_ms: int = 400, cap_ms: int = 8000) -> None:
    delay_ms = min(cap_ms, base_ms * (2**attempt))
    jitter = random.uniform(0, delay_ms * 0.25)
    await asyncio.sleep((delay_ms + jitter) / 1000)
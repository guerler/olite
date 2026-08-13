"""Retry utilities with exponential backoff."""

import asyncio
import logging
from typing import Awaitable, Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


async def retry_async(
    func: Callable[[], Awaitable[T]],
    max_retries: int = 3,
    initial_backoff: float = 1.0,
    retryable: Callable[[Exception], bool] | None = None,
    on_retry: Callable[[Exception, int, float], None] | None = None,
) -> T:
    """Execute an async function with retry and exponential backoff."""
    last_error: Exception | None = None

    for attempt in range(max_retries):
        try:
            return await func()
        except Exception as e:
            if retryable and not retryable(e):
                raise

            last_error = e

            if attempt < max_retries - 1:
                backoff = initial_backoff * (2**attempt)
                if on_retry:
                    on_retry(e, attempt + 1, backoff)
                await asyncio.sleep(backoff)

    # last_error is guaranteed to be set after at least one iteration
    if last_error is None:
        raise RuntimeError("Retry loop completed without capturing an error")
    raise last_error

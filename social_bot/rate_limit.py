from __future__ import annotations

import asyncio
import random
import httpx


class RateLimitError(RuntimeError):
    pass


async def request_with_backoff(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    max_attempts: int = 6,
    **kwargs,
) -> httpx.Response:
    for attempt in range(max_attempts):
        response = await client.request(method, url, **kwargs)
        if response.status_code != 429:
            response.raise_for_status()
            return response

        retry_after = response.headers.get("Retry-After")
        delay = float(retry_after) if retry_after and retry_after.isdigit() else min(
            60.0, (2**attempt) + random.random()
        )
        await asyncio.sleep(delay)

    raise RateLimitError(f"Rate limit persisted after {max_attempts} attempts: {url}")

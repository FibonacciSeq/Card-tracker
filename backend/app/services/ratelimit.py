"""Small in-process rate limiter for the endpoints worth protecting.

This is deliberately not a distributed system. It protects the login form and
public reservation creation from casual abuse in a single-process deployment;
when the API runs with multiple workers, back this with Redis instead.
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque

from fastapi import HTTPException, Request, status


class SlidingWindowLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def hit(
        self,
        key: str,
        *,
        limit: int,
        window_seconds: float,
        now: float | None = None,
    ) -> float | None:
        """Record an attempt. Returns None when allowed, else seconds to wait."""
        if limit <= 0:
            return None

        current = time.monotonic() if now is None else now
        cutoff = current - window_seconds
        with self._lock:
            bucket = self._hits.setdefault(key, deque())
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= limit:
                return max(0.0, bucket[0] + window_seconds - current)
            bucket.append(current)
            return None

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = SlidingWindowLimiter()


def client_key(request: Request, scope: str, extra: str = "") -> str:
    host = request.client.host if request.client else "unknown"
    return f"{scope}:{host}:{extra}" if extra else f"{scope}:{host}"


def enforce(
    request: Request,
    *,
    scope: str,
    limit: int,
    window_seconds: float,
    extra: str = "",
) -> None:
    retry_after = limiter.hit(
        client_key(request, scope, extra),
        limit=limit,
        window_seconds=window_seconds,
    )
    if retry_after is not None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many attempts. Please wait a moment and try again.",
            headers={"Retry-After": str(max(1, math.ceil(retry_after)))},
        )

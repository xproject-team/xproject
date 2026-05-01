"""Async token-bucket rate limiter — keeps us under Slesh's quota.

WHY THIS EXISTS:
Slesh enforces a per-token rate limit (returns HTTP 429 on exceed) but
does not document the actual number. Without our own limiter, a buggy
loop could fire thousands of calls in seconds, burn through quota, and
trigger Slesh's monitoring. With this limiter, the worst case is "the
loop runs slower" — never "Alberto gets paged at 22:00."

HOW THE TOKEN BUCKET WORKS:
- The bucket holds up to `capacity` tokens.
- Every call to `acquire()` removes 1 token.
- Tokens regenerate at `rate_per_sec` per second (continuously).
- If `acquire()` finds the bucket empty, it waits until 1 token is available.

This handles two patterns naturally:
  • BURST  — first N calls go instantly (bucket starts full)
  • STEADY — sustained throughput converges to `rate_per_sec`

DESIGN CHOICES:
- Defaults: capacity == rate_per_sec. Means "bucket holds 1 second of work."
  Very burst-friendly without long queue starvation. Configurable.
- Single async lock — no false races, no double-spend of tokens.
- Monotonic time — immune to wall-clock changes (NTP adjustments, DST).

USAGE:
    limiter = TokenBucketLimiter(rate_per_sec=5)
    for path in paths:
        await limiter.acquire()       # blocks until a token is free
        data = await client.get(path)

Spec: docs/slesh-integration-roadmap.md §B3.3
"""
from __future__ import annotations

import asyncio
import time


class TokenBucketLimiter:
    """Async, fair, per-instance token-bucket rate limiter.

    Each adapter instance gets its own limiter — there is no global state
    and no module-level singleton, so multiple adapters (test + prod, or
    a future second POS vendor) cannot starve each other.
    """

    def __init__(self, rate_per_sec: float, capacity: int | None = None):
        if rate_per_sec <= 0:
            raise ValueError(f"rate_per_sec must be > 0, got {rate_per_sec}")
        if capacity is not None and capacity <= 0:
            raise ValueError(f"capacity must be > 0 if specified, got {capacity}")

        self._rate     = float(rate_per_sec)
        self._capacity = float(capacity if capacity is not None else rate_per_sec)
        self._tokens   = self._capacity            # start full (allow first burst)
        self._last     = time.monotonic()
        self._lock     = asyncio.Lock()

    @property
    def rate_per_sec(self) -> float:
        return self._rate

    @property
    def capacity(self) -> float:
        return self._capacity

    async def acquire(self, n: int = 1) -> None:
        """Block until `n` tokens are available, then consume them.

        Args:
            n: how many tokens to acquire (default 1 — one HTTP call).

        Raises:
            ValueError if n is non-positive or larger than capacity.
        """
        if n <= 0:
            raise ValueError(f"acquire(n) needs n > 0, got {n}")
        if n > self._capacity:
            raise ValueError(
                f"acquire(n={n}) exceeds capacity={self._capacity:g}; "
                "either raise capacity or split the work."
            )

        # The lock keeps the refill+take operation atomic. Worst case for
        # contention is one async wait per concurrent caller; in practice
        # adapter usage is sequential per instance.
        while True:
            async with self._lock:
                self._refill()
                if self._tokens >= n:
                    self._tokens -= n
                    return
                # Compute exact sleep needed for `n` tokens to arrive
                shortfall = n - self._tokens
                wait      = shortfall / self._rate
            # Sleep OUTSIDE the lock so other callers can refill check.
            await asyncio.sleep(wait)

    # ── Internal: refill based on elapsed time since last touch ──────
    def _refill(self) -> None:
        now     = time.monotonic()
        elapsed = now - self._last
        if elapsed > 0:
            self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
            self._last   = now


__all__ = ["TokenBucketLimiter"]

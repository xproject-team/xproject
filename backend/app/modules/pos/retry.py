"""Exponential backoff retry + circuit breaker for the Slesh adapter.

WHY THIS EXISTS:
The limiter (limiter.py) keeps US well-behaved. This file handles SLESH
being unreliable. Two failure modes need graceful handling:

  1. Transient: Slesh returns 503 once, recovers in 2 seconds.
     -> retry with exponential backoff (1s, 2s, 4s) and recover smoothly.

  2. Sustained: Slesh is down for minutes. Retrying every call wastes
     quota and pegs CPU.
     -> circuit breaker opens after N consecutive failures. While open,
        all calls fail fast (no Slesh call attempted). After cooldown,
        a single probe call decides whether to close again.

WHAT GETS RETRIED (decided in B3.4):
  - SleshRateLimitError (429)        -> backoff and retry
  - SleshServerError    (5xx)        -> backoff and retry
  - httpx.RequestError  (network)    -> backoff and retry
What does NOT get retried:
  - SleshAuthError      (401/403)    -> token broken, retrying won't help
  - SleshClientError    (other 4xx)  -> request malformed, retry = same error

THRESHOLDS (industry-standard defaults, tunable via RetryPolicy):
  - max_retries:      3       (so 4 total attempts, with 1s/2s/4s delays)
  - base_delay:       1.0s
  - max_delay:        30.0s   (cap so we never sleep longer than this)
  - failures_to_open: 5       (Hystrix default — proven flap-resistant)
  - open_cooldown:    60.0s
  - probes_to_close:  1

USAGE:
    breaker = CircuitBreaker()
    policy  = RetryPolicy()

    async def call_slesh():
        return await client.get("/brand/my")

    result = await retry_with_backoff(call_slesh, policy=policy, breaker=breaker)

Spec: docs/slesh-integration-roadmap.md §B3.4
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import Enum
from typing import TypeVar

import httpx

from app.modules.pos.client import (
    SleshRateLimitError,
    SleshServerError,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")


# ─────────────────────────────────────────────────────────────────────
# Retry policy — pure data, configurable via constructor
# ─────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class RetryPolicy:
    """Tunable thresholds for retry-with-backoff behavior.

    Defaults match Hystrix / Polly / Resilience4j standards. Override
    individually if testing requires faster sequences.
    """
    max_retries: int   = 3              # 4 total attempts (initial + 3 retries)
    base_delay:  float = 1.0            # first retry waits this long
    max_delay:   float = 30.0           # cap on any individual sleep
    backoff_multiplier: float = 2.0     # exponential growth factor

    def delay_for(self, attempt: int) -> float:
        """Compute the sleep delay before retry attempt `attempt` (1-indexed).

        attempt=1 -> base_delay
        attempt=2 -> base_delay * multiplier
        attempt=3 -> base_delay * multiplier^2
        ... capped at max_delay.
        """
        if attempt < 1:
            raise ValueError(f"attempt must be >= 1, got {attempt}")
        delay = self.base_delay * (self.backoff_multiplier ** (attempt - 1))
        return min(delay, self.max_delay)


# ─────────────────────────────────────────────────────────────────────
# Circuit breaker — three-state machine
# ─────────────────────────────────────────────────────────────────────
class CircuitState(str, Enum):
    CLOSED    = "closed"      # normal operation
    OPEN      = "open"        # failing fast, no calls attempted
    HALF_OPEN = "half_open"   # probe period after cooldown


class CircuitBreakerOpen(Exception):
    """Raised when a call is blocked because the circuit is open.

    Distinct from any Slesh error so callers can choose: log and continue
    (poller skips this cycle), or surface to user (dashboard shows banner).
    """


class CircuitBreaker:
    """Per-adapter circuit breaker with the standard three-state machine.

    Not thread-safe; designed for single-task async use, which matches our
    polling worker model (one breaker per adapter instance).
    """

    def __init__(
        self,
        *,
        failures_to_open:  int   = 5,
        open_cooldown:     float = 60.0,
        probes_to_close:   int   = 1,
    ):
        if failures_to_open <= 0:
            raise ValueError("failures_to_open must be > 0")
        if open_cooldown <= 0:
            raise ValueError("open_cooldown must be > 0")
        if probes_to_close <= 0:
            raise ValueError("probes_to_close must be > 0")

        self._fail_threshold  = failures_to_open
        self._cooldown        = open_cooldown
        self._probe_threshold = probes_to_close

        self._state           = CircuitState.CLOSED
        self._consec_failures = 0
        self._consec_probes_ok = 0
        self._opened_at: float | None = None

    @property
    def state(self) -> CircuitState:
        return self._state

    def before_call(self) -> None:
        """Called before every attempted call. Raises if circuit is open."""
        if self._state == CircuitState.CLOSED:
            return
        if self._state == CircuitState.OPEN:
            # Has the cooldown elapsed? If so, transition to HALF_OPEN.
            assert self._opened_at is not None
            if time.monotonic() - self._opened_at >= self._cooldown:
                logger.info("Circuit breaker: OPEN -> HALF_OPEN (cooldown elapsed)")
                self._state           = CircuitState.HALF_OPEN
                self._consec_probes_ok = 0
                return
            raise CircuitBreakerOpen(
                f"Circuit open ({self._consec_failures} consecutive failures); "
                f"cooldown for {self._cooldown - (time.monotonic() - self._opened_at):.1f}s more"
            )
        # HALF_OPEN: allow the call through (it's a probe)
        return

    def on_success(self) -> None:
        """Call succeeded — reset failure counter, possibly close the circuit."""
        if self._state == CircuitState.HALF_OPEN:
            self._consec_probes_ok += 1
            if self._consec_probes_ok >= self._probe_threshold:
                logger.info("Circuit breaker: HALF_OPEN -> CLOSED (probe(s) succeeded)")
                self._state            = CircuitState.CLOSED
                self._consec_failures  = 0
                self._opened_at        = None
        else:
            # Reset failure counter even if we were already CLOSED
            self._consec_failures = 0

    def on_failure(self) -> None:
        """Call failed — increment counter, possibly open the circuit."""
        self._consec_failures += 1
        if self._state == CircuitState.HALF_OPEN:
            # Probe failed -> back to OPEN, reset cooldown timer
            logger.warning(
                "Circuit breaker: HALF_OPEN -> OPEN (probe failed)"
            )
            self._state     = CircuitState.OPEN
            self._opened_at = time.monotonic()
            self._consec_probes_ok = 0
            return
        if self._consec_failures >= self._fail_threshold:
            logger.warning(
                "Circuit breaker: CLOSED -> OPEN (%d consecutive failures)",
                self._consec_failures,
            )
            self._state     = CircuitState.OPEN
            self._opened_at = time.monotonic()


# ─────────────────────────────────────────────────────────────────────
# The wrapper — combine retry + circuit breaker around an async callable
# ─────────────────────────────────────────────────────────────────────
# Errors that the retry layer treats as "try again":
RETRYABLE_EXCEPTIONS: tuple[type[BaseException], ...] = (
    SleshRateLimitError,
    SleshServerError,
    httpx.RequestError,    # connection refused, timeouts, DNS, etc.
)


async def retry_with_backoff(
    operation: Callable[[], Awaitable[T]],
    *,
    policy:  RetryPolicy   | None = None,
    breaker: CircuitBreaker | None = None,
    op_name: str = "<unnamed op>",
) -> T:
    """Run `operation` with exponential backoff retry and circuit breaker.

    Args:
        operation: async callable taking no args, returning whatever the
                   underlying call returns.
        policy:    retry thresholds. None -> default RetryPolicy().
        breaker:   circuit breaker. None -> defaults; pass an explicit
                   instance to share state across calls (recommended).
        op_name:   human-readable identifier for logs.

    Returns:
        Whatever `operation` returns on first successful attempt.

    Raises:
        CircuitBreakerOpen   if the circuit is currently open.
        Whatever `operation` raises (non-retryable errors propagate
        immediately; retryable errors propagate after exhausting retries).
    """
    policy  = policy  or RetryPolicy()
    breaker = breaker or CircuitBreaker()

    last_exc: BaseException | None = None

    for attempt in range(policy.max_retries + 1):  # 0..N inclusive
        breaker.before_call()    # raises CircuitBreakerOpen if blocked

        try:
            result = await operation()
            breaker.on_success()
            if attempt > 0:
                logger.info(
                    "%s succeeded on attempt %d/%d after retry",
                    op_name, attempt + 1, policy.max_retries + 1,
                )
            return result

        except RETRYABLE_EXCEPTIONS as exc:
            breaker.on_failure()
            last_exc = exc
            if attempt >= policy.max_retries:
                logger.warning(
                    "%s exhausted %d retries: %s",
                    op_name, policy.max_retries, exc,
                )
                raise
            delay = policy.delay_for(attempt + 1)
            logger.info(
                "%s attempt %d failed (%s); retrying in %.1fs",
                op_name, attempt + 1, type(exc).__name__, delay,
            )
            await asyncio.sleep(delay)
            continue

        except BaseException:
            # Non-retryable: don't increment breaker (the call's defective,
            # not Slesh), let it propagate.
            raise

    # Defensive: shouldn't reach here, but if loop exits cleanly something's wrong
    assert last_exc is not None, "retry loop exited without success or exception"
    raise last_exc


__all__ = [
    "RetryPolicy",
    "CircuitState",
    "CircuitBreaker",
    "CircuitBreakerOpen",
    "retry_with_backoff",
    "RETRYABLE_EXCEPTIONS",
]

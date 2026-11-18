"""Rate limiting: a fixed-window counter per (rule, identity).

Why it exists (docs/architecture.md section 8): login throttling against password guessing,
registration throttling against account spam, and per-user caps on the routes that cost
money or CPU (questions go to a paid/free-tier model, uploads trigger embedding).

* Counters live in Redis (``INCR`` + ``EXPIRE``), so the limit holds across API processes.
* A fixed window is simple and cheap; its known weakness is that a client can use the
  full limit at the end of one window and again at the start of the next (2x for an
  instant). That is acceptable for abuse protection; it is not a billing meter.
* **Fails open**: if Redis is down or slow, requests are allowed and a warning is logged.
  A cache outage must not take the application down with it; the health check reports it.
* Limits are written ``<count>/<window>`` with window units s, m or h: ``10/1m``, ``5/15m``.
"""

import asyncio
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from redis.asyncio import Redis

logger = logging.getLogger(__name__)

_RULE = re.compile(r"^(?P<count>[1-9]\d*)/(?P<window>[1-9]\d*)(?P<unit>[smh])$")
_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600}

# Redis answers in well under a millisecond; this only bounds the damage of a hung server.
_REDIS_TIMEOUT_SECONDS = 0.5


@dataclass(frozen=True)
class Rule:
    limit: int
    window_seconds: int

    @classmethod
    def parse(cls, text: str) -> "Rule":
        match = _RULE.match(text.strip())
        if not match:
            raise ValueError(f"invalid rate limit {text!r}; expected e.g. 10/1m, 5/15m or 100/1h")
        return cls(
            limit=int(match["count"]),
            window_seconds=int(match["window"]) * _UNIT_SECONDS[match["unit"]],
        )


@dataclass(frozen=True)
class Decision:
    allowed: bool
    retry_after_seconds: int = 0


class RateLimiter(Protocol):
    async def hit(self, key: str, rule: Rule) -> Decision:
        """Count one request against ``key`` and say whether it is within ``rule``."""
        ...


class RedisRateLimiter:
    def __init__(self, get_redis: Callable[[], Redis]) -> None:
        # A callable, because the client is created in the application's lifespan.
        self._get_redis = get_redis

    async def hit(self, key: str, rule: Rule) -> Decision:
        redis_key = f"ratelimit:{key}"
        try:
            async with asyncio.timeout(_REDIS_TIMEOUT_SECONDS):
                redis = self._get_redis()
                async with redis.pipeline(transaction=True) as pipe:
                    # NX: the window starts at the first request and is not extended by later ones.
                    pipe.incr(redis_key)
                    pipe.expire(redis_key, rule.window_seconds, nx=True)
                    pipe.ttl(redis_key)
                    count, _, ttl = await pipe.execute()
        except Exception:  # noqa: BLE001 - any Redis failure must fail open, never fail the request
            logger.warning("rate limiter unavailable; allowing the request", exc_info=True)
            return Decision(allowed=True)
        if count > rule.limit:
            return Decision(allowed=False, retry_after_seconds=max(int(ttl), 1))
        return Decision(allowed=True)


class InMemoryRateLimiter:
    """Same behaviour in one process. For tests and single-process development."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._windows: dict[str, tuple[float, int]] = {}

    async def hit(self, key: str, rule: Rule) -> Decision:
        now = self._clock()
        started, count = self._windows.get(key, (now, 0))
        if now - started >= rule.window_seconds:
            started, count = now, 0
        count += 1
        self._windows[key] = (started, count)
        if count > rule.limit:
            return Decision(
                allowed=False,
                retry_after_seconds=max(int(started + rule.window_seconds - now) + 1, 1),
            )
        return Decision(allowed=True)


class DisabledRateLimiter:
    async def hit(self, key: str, rule: Rule) -> Decision:  # noqa: ARG002
        return Decision(allowed=True)

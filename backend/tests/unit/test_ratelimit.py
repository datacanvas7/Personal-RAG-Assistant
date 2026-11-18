"""The rate limiter: rule parsing, window behaviour, Redis counters and failing open."""

import pytest

from app.core.ratelimit import (
    DisabledRateLimiter,
    InMemoryRateLimiter,
    RedisRateLimiter,
    Rule,
)


@pytest.mark.parametrize(
    ("text", "limit", "seconds"),
    [
        ("10/1m", 10, 60),
        ("5/15m", 5, 900),
        ("100/1h", 100, 3600),
        ("3/30s", 3, 30),
        (" 7/2m ", 7, 120),
    ],
)
def test_rule_parses_count_and_window(text: str, limit: int, seconds: int) -> None:
    rule = Rule.parse(text)

    assert rule.limit == limit
    assert rule.window_seconds == seconds


@pytest.mark.parametrize("text", ["", "10", "10/m", "0/1m", "10/0m", "10/1d", "-1/1m", "ten/1m"])
def test_rule_rejects_malformed_text(text: str) -> None:
    with pytest.raises(ValueError, match="invalid rate limit"):
        Rule.parse(text)


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


async def test_in_memory_allows_up_to_the_limit_then_blocks() -> None:
    limiter = InMemoryRateLimiter(clock=Clock())
    rule = Rule(limit=3, window_seconds=60)

    decisions = [await limiter.hit("k", rule) for _ in range(5)]

    assert [d.allowed for d in decisions] == [True, True, True, False, False]
    assert decisions[3].retry_after_seconds >= 1


async def test_in_memory_counts_each_key_separately() -> None:
    limiter = InMemoryRateLimiter(clock=Clock())
    rule = Rule(limit=1, window_seconds=60)

    assert (await limiter.hit("ada", rule)).allowed
    assert (await limiter.hit("bob", rule)).allowed
    assert not (await limiter.hit("ada", rule)).allowed


async def test_in_memory_window_resets_after_it_elapses() -> None:
    clock = Clock()
    limiter = InMemoryRateLimiter(clock=clock)
    rule = Rule(limit=1, window_seconds=60)
    await limiter.hit("k", rule)
    assert not (await limiter.hit("k", rule)).allowed

    clock.now += 61

    assert (await limiter.hit("k", rule)).allowed


async def test_in_memory_retry_after_shrinks_as_the_window_runs_out() -> None:
    clock = Clock()
    limiter = InMemoryRateLimiter(clock=clock)
    rule = Rule(limit=1, window_seconds=60)
    await limiter.hit("k", rule)
    first = await limiter.hit("k", rule)
    clock.now += 40

    later = await limiter.hit("k", rule)

    assert later.retry_after_seconds < first.retry_after_seconds


async def test_disabled_limiter_always_allows() -> None:
    limiter = DisabledRateLimiter()

    decisions = [await limiter.hit("k", Rule(1, 60)) for _ in range(10)]

    assert all(d.allowed for d in decisions)


class FakePipeline:
    """Just enough of redis.asyncio's pipeline for INCR / EXPIRE NX / TTL."""

    def __init__(self, redis: "FakeRedis") -> None:
        self._redis = redis
        self._commands: list[tuple[str, tuple[object, ...], dict[str, object]]] = []

    async def __aenter__(self) -> "FakePipeline":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    def incr(self, key: str) -> None:
        self._commands.append(("incr", (key,), {}))

    def expire(self, key: str, seconds: int, **kwargs: object) -> None:
        self._commands.append(("expire", (key, seconds), kwargs))

    def ttl(self, key: str) -> None:
        self._commands.append(("ttl", (key,), {}))

    async def execute(self) -> list[int]:
        if self._redis.fail:
            raise ConnectionError("redis is down")
        results: list[int] = []
        for name, args, kwargs in self._commands:
            results.append(getattr(self._redis, f"_{name}")(*args, **kwargs))
        return results


class FakeRedis:
    def __init__(self) -> None:
        self.counts: dict[str, int] = {}
        self.ttls: dict[str, int] = {}
        self.fail = False

    def pipeline(self, transaction: bool = True) -> FakePipeline:  # noqa: ARG002
        return FakePipeline(self)

    def _incr(self, key: str) -> int:
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    def _expire(self, key: str, seconds: int, nx: bool = False) -> int:
        if nx and key in self.ttls:
            return 0
        self.ttls[key] = seconds
        return 1

    def _ttl(self, key: str) -> int:
        return self.ttls.get(key, -1)


async def test_redis_limiter_counts_in_a_namespaced_key_and_blocks_over_the_limit() -> None:
    redis = FakeRedis()
    limiter = RedisRateLimiter(lambda: redis)  # type: ignore[arg-type,return-value]
    rule = Rule(limit=2, window_seconds=90)

    decisions = [await limiter.hit("login_ip:1.2.3.4", rule) for _ in range(3)]

    assert [d.allowed for d in decisions] == [True, True, False]
    assert decisions[2].retry_after_seconds == 90
    assert list(redis.counts) == ["ratelimit:login_ip:1.2.3.4"]


async def test_redis_limiter_sets_the_window_only_once() -> None:
    redis = FakeRedis()
    limiter = RedisRateLimiter(lambda: redis)  # type: ignore[arg-type,return-value]
    rule = Rule(limit=5, window_seconds=60)
    await limiter.hit("k", rule)
    redis.ttls["ratelimit:k"] = 17  # time has passed in the window

    await limiter.hit("k", rule)

    assert redis.ttls["ratelimit:k"] == 17  # a later request does not extend the window


async def test_redis_limiter_fails_open_when_redis_is_down(
    caplog: pytest.LogCaptureFixture,
) -> None:
    redis = FakeRedis()
    redis.fail = True
    limiter = RedisRateLimiter(lambda: redis)  # type: ignore[arg-type,return-value]

    decision = await limiter.hit("k", Rule(limit=1, window_seconds=60))

    assert decision.allowed
    assert "rate limiter unavailable" in caplog.text


async def test_redis_limiter_fails_open_when_the_client_does_not_exist_yet() -> None:
    def no_client() -> object:
        raise AttributeError("redis")

    limiter = RedisRateLimiter(no_client)  # type: ignore[arg-type]

    assert (await limiter.hit("k", Rule(limit=1, window_seconds=60))).allowed

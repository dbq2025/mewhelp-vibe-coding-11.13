"""限流器单测：窗口、配额、重试等待、关闭开关、键回收。

时间用真实 `monotonic` + 极短窗口（50ms），不 mock 时间——滑窗逻辑的 bug 几乎都
出在"边界那一下"，mock 时间容易把边界一起 mock 掉。
"""

from __future__ import annotations

import time

from app.core.ratelimit import SlidingWindowLimiter


def test_allows_up_to_limit_then_blocks() -> None:
    limiter = SlidingWindowLimiter(limit=3, window_seconds=60)
    assert [limiter.hit("ip")[0] for _ in range(3)] == [True, True, True]
    allowed, retry_after = limiter.hit("ip")
    assert allowed is False
    assert 0 < retry_after <= 60


def test_keys_are_independent() -> None:
    limiter = SlidingWindowLimiter(limit=1, window_seconds=60)
    assert limiter.hit("a")[0] is True
    assert limiter.hit("a")[0] is False
    assert limiter.hit("b")[0] is True


def test_slot_frees_after_window() -> None:
    limiter = SlidingWindowLimiter(limit=1, window_seconds=0.05)
    assert limiter.hit("ip")[0] is True
    assert limiter.hit("ip")[0] is False
    time.sleep(0.07)
    assert limiter.hit("ip")[0] is True


def test_zero_limit_disables() -> None:
    limiter = SlidingWindowLimiter(limit=0, window_seconds=60)
    assert limiter.enabled() is False
    assert all(limiter.hit("ip")[0] for _ in range(100))


def test_reset_clears_bucket() -> None:
    limiter = SlidingWindowLimiter(limit=1, window_seconds=60)
    assert limiter.hit("a")[0] is True
    assert limiter.hit("a")[0] is False
    limiter.reset("a")
    assert limiter.hit("a")[0] is True
    limiter.reset()
    assert limiter._hits == {}


def test_throttle_stats_counted() -> None:
    limiter = SlidingWindowLimiter(limit=1, window_seconds=60)
    limiter.hit("ip")
    limiter.hit("ip")
    limiter.hit("ip")
    assert limiter.stats.total == 2
    assert limiter.stats.last_minute() == 2


def test_stale_keys_are_swept() -> None:
    """键只增不减会泄漏内存：超过阈值后，整窗空闲的 key 必须被回收。"""
    limiter = SlidingWindowLimiter(limit=5, window_seconds=0.05)
    for index in range(2100):
        limiter.hit(f"ip-{index}")
    time.sleep(0.07)
    limiter.hit("fresh")  # 触发 _sweep
    assert len(limiter._hits) < 2100

"""HTTP 层限流：按 IP 的进程内滑动窗口（计划 6.5 / P4 验收第 4 条）。

三个设计决定，都是有意的：

1. **为什么在中间件**：限流是横切关注点。放在路由里要么漏掉某个端点，要么每个端点
   复制一遍 `if not limiter.hit(): raise`。中间件只写一次，新加端点自动受保护。
2. **为什么按 IP 而不是按用户**：`/auth/login` 是未登录接口，按用户等于没限；
   IP 维度能同时挡住"换号刷"和"脚本撞库"。代价是同一出口 IP 的多个用户共享配额，
   本地单机部署可以接受（多实例/公网必须换 Redis + 用户维度，已在计划里标注）。
3. **为什么 0 表示关闭**：`scripts/eval.py` 一分钟要发上百个请求，它跑的是"功能正确性"
   而不是"配额正确性"；用配置关掉比给脚本开后门（伪造 IP/白名单头）安全得多。

响应口径与 `docs/api.md` 一致：429 + envelope，`code=4029`，带 `Retry-After`。
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field

from starlette.middleware.base import RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import get_settings
from app.core.errors import CODE_RATE_LIMITED
from app.core.logging import get_logger
from app.core.trace import get_trace_id

logger = get_logger(__name__)

# 这些路径不计入配额：健康检查被前端每 30s 轮询一次，限流会把它打成红色告警
_EXEMPT_PATHS = frozenset({"/health", "/openapi.json", "/docs", "/redoc"})

RATE_LIMIT_MESSAGE = "请求太频繁了，请等几秒再试。如果是连续提问，稍等一下我马上处理。"


@dataclass
class ThrottleStats:
    """被限流次数。放内存而不是埋 DB：它是"网关自身"的指标，写库会形成故障放大。"""

    total: int = 0
    recent: deque[float] = field(default_factory=deque)

    def record(self) -> None:
        now = time.monotonic()
        self.total += 1
        self.recent.append(now)
        cutoff = now - 60.0
        while self.recent and self.recent[0] < cutoff:
            self.recent.popleft()

    def last_minute(self) -> int:
        cutoff = time.monotonic() - 60.0
        while self.recent and self.recent[0] < cutoff:
            self.recent.popleft()
        return len(self.recent)


class SlidingWindowLimiter:
    """最朴素的滑动窗口：每个 key 一个时间戳队列，超窗淘汰。

    复杂度 O(窗口内请求数)，本项目量级（30/分钟）完全够用，
    不需要令牌桶的平滑效果——我们要的是"挡住刷子"，不是"整形流量"。
    """

    def __init__(self, limit: int, window_seconds: float = 60.0) -> None:
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = {}
        self.stats = ThrottleStats()

    def configure(self, *, limit: int, window_seconds: float) -> None:
        """运行期改配额（测试与热调都用它，避免重建对象丢统计）。"""
        self.limit = limit
        self.window = window_seconds
        self._hits.clear()

    def enabled(self) -> bool:
        return self.limit > 0

    def hit(self, key: str) -> tuple[bool, float]:
        """返回 (是否放行, 建议等待秒数)。配额为 0 时一律放行。"""
        if not self.enabled():
            return True, 0.0
        now = time.monotonic()
        bucket = self._hits.setdefault(key, deque())
        cutoff = now - self.window
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()
        if len(bucket) >= self.limit:
            # 最早那次请求滑出窗口时才腾出名额
            retry_after = max(0.0, self.window - (now - bucket[0]))
            self.stats.record()
            return False, retry_after
        bucket.append(now)
        self._sweep(now)
        return True, 0.0

    def reset(self, key: str | None = None) -> None:
        if key is None:
            self._hits.clear()
            return
        self._hits.pop(key, None)

    def _sweep(self, now: float) -> None:
        """键只增不减会泄漏内存：键数超过阈值时清掉整窗空闲的 key。"""
        if len(self._hits) <= 2048:
            return
        cutoff = now - self.window
        for key in [k for k, v in self._hits.items() if not v or v[-1] <= cutoff]:
            self._hits.pop(key, None)


_settings = get_settings()
limiter = SlidingWindowLimiter(
    limit=_settings.rate_limit_per_minute,
    window_seconds=_settings.rate_limit_window_seconds,
)


def client_key(request: Request) -> str:
    """限流键。

    不信任 `X-Forwarded-For`：本地单机没有反向代理，凭客户端可伪造的头做限流
    等于给了"换个头就绕过"的开关。
    """
    client = request.client
    return client.host if client is not None else "unknown"


def _envelope(code: int, message: str) -> dict[str, object]:
    return {"code": code, "message": message, "data": None, "traceId": get_trace_id()}


async def rate_limit_middleware(request: Request, call_next: RequestResponseEndpoint) -> Response:
    if request.url.path in _EXEMPT_PATHS or not limiter.enabled():
        return await call_next(request)

    allowed, retry_after = limiter.hit(client_key(request))
    if not allowed:
        wait = max(1, int(retry_after + 0.999))
        logger.warning("http_rate_limited", path=request.url.path, retry_after=wait)
        return JSONResponse(
            status_code=429,
            content=_envelope(CODE_RATE_LIMITED, RATE_LIMIT_MESSAGE),
            headers={
                "Retry-After": str(wait),
                "X-RateLimit-Limit": str(limiter.limit),
            },
        )

    response = await call_next(request)
    response.headers["X-RateLimit-Limit"] = str(limiter.limit)
    return response


def read_limit_from_config() -> tuple[int, float]:
    """启动时把配置灌进单例。测试里也走这里，保证口径一致。"""
    settings = get_settings()
    limiter.configure(
        limit=settings.rate_limit_per_minute,
        window_seconds=settings.rate_limit_window_seconds,
    )
    return limiter.limit, limiter.window

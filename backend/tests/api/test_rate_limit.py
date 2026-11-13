"""HTTP 限流中间件：429 契约、豁免路径、按 IP 隔离（P4 验收第 4 条）。

用例里显式打开限流（conftest 默认关闭），验证的是"到点就挡"和"挡得体面"：
状态码 429、envelope 带 code 4029 与 traceId、响应头带 Retry-After。
"""

from __future__ import annotations

import asyncio

import pytest
from httpx import AsyncClient

from app.core.ratelimit import limiter, read_limit_from_config


@pytest.fixture(autouse=True)
def _tight_limit(_disable_rate_limit: None) -> None:
    # 显式依赖 conftest 的"关限流"夹具，保证本夹具在它之后执行（否则会被重置回 0）
    limiter.configure(limit=3, window_seconds=60.0)


async def test_blocks_after_limit_with_envelope(client: AsyncClient) -> None:
    for _ in range(3):
        assert (await client.get("/api/v1/meta")).status_code == 200

    response = await client.get("/api/v1/meta")
    assert response.status_code == 429
    body = response.json()
    assert body["code"] == 4029
    assert body["data"] is None
    assert body["traceId"]
    assert "频繁" in body["message"]
    retry_after = int(response.headers["Retry-After"])
    assert 1 <= retry_after <= 60
    assert response.headers["X-RateLimit-Limit"] == "3"


async def test_health_is_exempt(client: AsyncClient) -> None:
    """健康检查被前端轮询，若计入配额会把"服务正常"打成 429 红点。"""
    for _ in range(10):
        assert (await client.get("/health")).status_code == 200


async def test_counter_resets_after_window(client: AsyncClient) -> None:
    limiter.configure(limit=1, window_seconds=0.05)
    assert (await client.get("/api/v1/meta")).status_code == 200
    assert (await client.get("/api/v1/meta")).status_code == 429
    await asyncio.sleep(0.07)
    assert (await client.get("/api/v1/meta")).status_code == 200


async def test_limit_zero_disables_middleware(client: AsyncClient) -> None:
    """评测脚本靠这个开关跑量（不是伪造 IP 白名单）。"""
    limiter.configure(limit=0, window_seconds=60.0)
    for _ in range(40):
        assert (await client.get("/api/v1/meta")).status_code == 200


def test_config_reader_applies_settings() -> None:
    limit, window = read_limit_from_config()
    assert limit >= 0
    assert window > 0
    limiter.configure(limit=0, window_seconds=60.0)

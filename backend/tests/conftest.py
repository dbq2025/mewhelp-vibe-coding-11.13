"""测试公共夹具。

约定（agent.md §9）：数据库测试打真实 Postgres，不 mock session；
LLM 一律 Fake。P0 只有健康检查，因此只依赖应用实例与 ASGI transport。

Windows 上的坑：pytest-asyncio 默认每个用例一个事件循环，而 SQLAlchemy 的
连接池是模块级全局的，连接会挂在已关闭的循环上（报 "Event loop is closed"）。
解决办法是用例级 teardown 主动 dispose，让下一个用例在新循环里重建连接。
"""

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from app.infra.db.session import dispose_engine
from app.main import app


@pytest.fixture(autouse=True)
async def _dispose_engine_after_test() -> AsyncIterator[None]:
    yield
    await dispose_engine()


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

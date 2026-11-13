"""测试公共夹具。

约定（agent.md §9）：数据库打真实 Postgres，不 mock session；LLM/Embedding 一律 Fake。

两个环境相关处理：
1. Windows 上 SQLAlchemy 连接池挂在已关闭的事件循环 → 每个用例结束 dispose engine；
2. 商品/订单类用例依赖 seed 数据，首次运行时自动灌一次（幂等脚本），
   避免"必须先手动跑 seed 才能测"的隐性前置。
"""

from __future__ import annotations

import importlib.util
from collections.abc import AsyncIterator
from pathlib import Path
from types import ModuleType

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.infra.db.models.catalog import Product
from app.infra.db.session import SessionFactory, dispose_engine
from app.main import app

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_seed_checked = False


def _load_seed_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "seed_script", _BACKEND_ROOT / "scripts" / "seed.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
async def _dispose_engine_after_test() -> AsyncIterator[None]:
    yield
    await dispose_engine()


@pytest.fixture(autouse=True)
async def ensure_seed() -> None:
    """库里没有任何商品时灌一次演示数据（幂等，不会重复写）。"""
    global _seed_checked
    if _seed_checked:
        return
    async with SessionFactory() as session:
        count = int(await session.scalar(select(func.count()).select_from(Product)) or 0)
    if count == 0:
        await _load_seed_module().seed()
    _seed_checked = True


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def auth_client(client: AsyncClient) -> AsyncClient:
    """登录主测账号 A，后续请求自动带 token。"""
    response = await client.post(
        "/api/v1/auth/login", json={"phone": "13800000001", "password": "Test123456"}
    )
    assert response.status_code == 200, response.text
    token = response.json()["data"]["token"]
    client.headers["Authorization"] = f"Bearer {token}"
    return client

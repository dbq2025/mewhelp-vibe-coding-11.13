"""会话 CRUD 与历史消息接口。"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.infra.db.models.chat import ChatSession
from app.infra.db.models.ops import LlmUsage
from app.infra.db.session import SessionFactory


@pytest.fixture(autouse=True)
async def _cleanup_sessions() -> AsyncIterator[None]:
    """按「测试前后差集」清理会话，而不是整表清空。

    整表清空会连开发者手工测出来的会话历史一起删掉（P4 实测踩到：
    跑一次 pytest，侧边栏记录和 llm_usage 计量都没了）。差集法只回收
    本用例新造出来的行，测试之间也不依赖执行顺序。
    """
    async with SessionFactory() as session:
        before = set((await session.scalars(select(ChatSession.id))).all())
    yield
    async with SessionFactory() as session:
        stale = [
            row
            for row in (await session.scalars(select(ChatSession.id))).all()
            if row not in before
        ]
        if stale:
            # 消息随会话级联删除；llm_usage 没有外键，必须显式回收，
            # 否则测试会把"看不见轮次、只看见成本"的脏数据留在看板里
            await session.execute(delete(LlmUsage).where(LlmUsage.session_id.in_(stale)))
            await session.execute(delete(ChatSession).where(ChatSession.id.in_(stale)))
        await session.commit()


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _login(client: AsyncClient, phone: str = "13800000001") -> str:
    response = await client.post(
        "/api/v1/auth/login", json={"phone": phone, "password": "Test123456"}
    )
    assert response.status_code == 200, response.text
    return str(response.json()["data"]["token"])


async def test_create_and_list_sessions(client: AsyncClient) -> None:
    token = await _login(client)
    created = await client.post(
        "/api/v1/sessions", json={"title": "耳机咨询"}, headers=_auth(token)
    )
    assert created.status_code == 201
    session_id = created.json()["data"]["id"]

    listed = await client.get("/api/v1/sessions", headers=_auth(token))
    assert listed.status_code == 200
    ids = [item["id"] for item in listed.json()["data"]["items"]]
    assert session_id in ids


async def test_rename_session(client: AsyncClient) -> None:
    token = await _login(client)
    created = await client.post("/api/v1/sessions", json={}, headers=_auth(token))
    session_id = created.json()["data"]["id"]

    renamed = await client.patch(
        f"/api/v1/sessions/{session_id}", json={"title": "退换货"}, headers=_auth(token)
    )
    assert renamed.status_code == 200
    assert renamed.json()["data"]["title"] == "退换货"


async def test_soft_delete_session_disappears_from_list(client: AsyncClient) -> None:
    token = await _login(client)
    created = await client.post("/api/v1/sessions", json={}, headers=_auth(token))
    session_id = created.json()["data"]["id"]

    deleted = await client.delete(f"/api/v1/sessions/{session_id}", headers=_auth(token))
    assert deleted.status_code == 200

    listed = await client.get("/api/v1/sessions", headers=_auth(token))
    assert session_id not in [item["id"] for item in listed.json()["data"]["items"]]


async def test_other_user_session_returns_404(client: AsyncClient) -> None:
    owner = await _login(client, "13800000001")
    created = await client.post("/api/v1/sessions", json={}, headers=_auth(owner))
    session_id = created.json()["data"]["id"]

    intruder = await _login(client, "13800000002")
    response = await client.get(f"/api/v1/sessions/{session_id}/messages", headers=_auth(intruder))
    # 不存在与不属于本人同码，避免会话 id 探测
    assert response.status_code == 404


async def test_sessions_require_auth(client: AsyncClient) -> None:
    response = await client.get("/api/v1/sessions")
    assert response.status_code == 401


async def test_messages_empty_for_new_session(client: AsyncClient) -> None:
    token = await _login(client)
    created = await client.post("/api/v1/sessions", json={}, headers=_auth(token))
    session_id = created.json()["data"]["id"]

    response = await client.get(f"/api/v1/sessions/{session_id}/messages", headers=_auth(token))
    assert response.status_code == 200
    assert response.json()["data"]["items"] == []

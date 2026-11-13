"""LLM 计量埋点与运维看板（P4）。

两个断言思路：
1. `llm_usage` 计量必须落在**真实调用**上：一轮里理解 1 次 + 生成 1 次 = 2 行，
   而且带着同一个 traceId —— 否则账对不上轮次；
2. `/admin/metrics` 是"运维看的页面"，所以它必须**挡住没口令的人**，也必须**不含 PII**。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.agent.llm import set_llm_client
from app.core.config import get_settings
from app.infra.db.models.chat import ChatSession
from app.infra.db.models.ops import LlmUsage
from app.infra.db.session import SessionFactory
from tests.fakes.fake_llm import FakeLlm, plan

PHONE = "13800000001"
PASSWORD = "Test123456"


_created: list[str] = []


@pytest.fixture(autouse=True)
async def _cleanup() -> AsyncIterator[None]:
    """只删本文件造出来的数据。

    早期版本这里 `delete(LlmUsage)` 整表清空，跑一次测试就把开发库里的真实计量
    和看板数据全抹了（P4 实测踩到：评测刚跑完的 140 条计量被 pytest 清成 0）。
    测试清理必须按 id 精确回收，不能"顺手清表"。
    """
    yield
    set_llm_client(None)
    async with SessionFactory() as session:
        if _created:
            await session.execute(delete(LlmUsage).where(LlmUsage.session_id.in_(_created)))
            await session.execute(delete(ChatSession).where(ChatSession.id.in_(_created)))
            await session.commit()
        _created.clear()


async def _login(client: AsyncClient) -> str:
    response = await client.post("/api/v1/auth/login", json={"phone": PHONE, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return str(response.json()["data"]["token"])


async def _chat_once(client: AsyncClient, token: str) -> str:
    created = await client.post(
        "/api/v1/sessions", json={}, headers={"Authorization": f"Bearer {token}"}
    )
    session_id = str(created.json()["data"]["id"])
    _created.append(session_id)
    async with client.stream(
        "POST",
        "/api/v1/chat/stream",
        json={"sessionId": session_id, "message": "你好，在吗", "clientMsgId": "p4-usage"},
        headers={"Authorization": f"Bearer {token}"},
    ) as response:
        assert response.status_code == 200
        async for _ in response.aiter_text():
            pass
    return session_id


async def test_turn_records_llm_usage(client: AsyncClient) -> None:
    set_llm_client(
        FakeLlm(plans=[plan(intent="chitchat", confidence=0.9)], answers=["在的，你说。"])
    )
    token = await _login(client)
    session_id = await _chat_once(client, token)

    async with SessionFactory() as session:
        rows = list(
            (
                await session.scalars(
                    select(LlmUsage).where(LlmUsage.session_id == UUID(session_id))
                )
            ).all()
        )

    # 一次理解 + 一次生成
    assert len(rows) == 2
    assert {row.trace_id for row in rows} == {rows[0].trace_id}
    assert all(row.model == get_settings().llm_model for row in rows)
    assert all(row.ok is True and row.error_code is None for row in rows)
    assert sum(row.prompt_tokens for row in rows) == 400  # 100(理解) + 300(生成)


async def _metrics(client: AsyncClient, token: str | None = None, **params: Any) -> Any:
    headers = {"X-Admin-Token": token} if token is not None else {}
    return await client.get("/api/v1/admin/metrics", headers=headers, params=params)


async def test_metrics_requires_admin_token(client: AsyncClient) -> None:
    settings = get_settings()
    original = settings.admin_token
    settings.admin_token = "secret-token"
    try:
        unset = await _metrics(client)
        assert unset.status_code == 403  # 已启用但没带口令 → 拒绝，且不给"口令对不对"的更多信息

        wrong = await _metrics(client, "nope")
        assert wrong.status_code == 403
        assert wrong.json()["code"] == 2003

        good = await _metrics(client, "secret-token")
        assert good.status_code == 200
        payload = good.json()["data"]
        assert set(payload) >= {
            "windowHours",
            "turns",
            "latencyMs",
            "llm",
            "intent",
            "tools",
            "afterSales",
            "handoff",
            "security",
        }
        assert payload["llm"]["costCny"] >= 0
        assert payload["security"]["rateLimitPerMinute"] >= 0
    finally:
        settings.admin_token = original


async def test_metrics_disabled_when_token_unset(client: AsyncClient) -> None:
    settings = get_settings()
    original = settings.admin_token
    settings.admin_token = ""
    try:
        response = await _metrics(client, "")
        assert response.status_code == 404
    finally:
        settings.admin_token = original


async def test_metrics_has_no_pii(client: AsyncClient) -> None:
    settings = get_settings()
    original = settings.admin_token
    settings.admin_token = "secret-token"
    try:
        await _chat_once_for_metrics(client)
        response = await _metrics(client, "secret-token", hours=1)
        raw = response.text
        assert response.status_code == 200
        # 看板只给聚合值：手机号、订单号、消息正文一律不能出现
        assert PHONE not in raw
        assert "202611010" not in raw
        assert "你好，在吗" not in raw
    finally:
        settings.admin_token = original


async def _chat_once_for_metrics(client: AsyncClient) -> None:
    set_llm_client(FakeLlm(plans=[plan(intent="chitchat", confidence=0.9)], answers=["嗯。"]))
    token = await _login(client)
    await _chat_once(client, token)

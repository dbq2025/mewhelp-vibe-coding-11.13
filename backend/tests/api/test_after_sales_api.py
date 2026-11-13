"""售后 / 转人工接口测试（P3 验收第 4 条）。

覆盖：建单成功、幂等不重复、越权 403、不可受理 400、未登录 401、
我的售后单列表、转人工幂等与状态机非法流转。

写库用例必须自行回收（agent.md §9）：所有建出来的工单在 teardown 按 ticket_no 删除，
否则跑几次之后 `after_sales` 行数就和 seed 对不上了。
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from httpx import AsyncClient
from sqlalchemy import delete

from app.infra.db.models.ops import HandoffTicket
from app.infra.db.models.order import AfterSale
from app.infra.db.session import SessionFactory

A_SHIPPED = "20261101008"  # A 的已发货单
A_CLOSED = "20261101005"  # A 的已关闭单
B_ORDER = "20261101023"  # B 的单，用于越权

_created_tickets: list[str] = []
_created_handoffs: list[str] = []


@pytest.fixture(autouse=True)
async def _cleanup() -> AsyncIterator[None]:
    yield
    if _created_tickets:
        async with SessionFactory() as session:
            await session.execute(
                delete(AfterSale).where(AfterSale.ticket_no.in_(_created_tickets))
            )
            await session.commit()
        _created_tickets.clear()
    if _created_handoffs:
        async with SessionFactory() as session:
            await session.execute(
                delete(HandoffTicket).where(HandoffTicket.ticket_no.in_(_created_handoffs))
            )
            await session.commit()
        _created_handoffs.clear()


async def test_create_after_sale_requires_login(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/after-sales", json={"orderNo": A_SHIPPED, "type": "return"}
    )
    assert response.status_code == 401
    assert response.json()["code"] == 2001


async def test_create_after_sale_ok(auth_client: AsyncClient) -> None:
    response = await auth_client.post(
        "/api/v1/after-sales",
        json={"orderNo": A_SHIPPED, "type": "return", "reason": "耳机有杂音"},
    )
    assert response.status_code == 201, response.text
    data = response.json()["data"]
    _created_tickets.append(data["ticketNo"])
    assert data["ticketNo"].startswith("AS")
    assert data["status"] == "pending"
    assert data["typeLabel"] == "退货退款"
    assert data["created"] is True


async def test_create_after_sale_is_idempotent(auth_client: AsyncClient) -> None:
    """同订单同类型重复提交只留一张单：用户连点两次不能变两张退货单。"""
    first = await auth_client.post(
        "/api/v1/after-sales", json={"orderNo": A_SHIPPED, "type": "return"}
    )
    second = await auth_client.post(
        "/api/v1/after-sales", json={"orderNo": A_SHIPPED, "type": "return"}
    )
    assert first.status_code == 201 and second.status_code == 201
    a = first.json()["data"]
    b = second.json()["data"]
    _created_tickets.append(a["ticketNo"])
    assert a["ticketNo"] == b["ticketNo"]
    assert b["created"] is False

    async with SessionFactory() as session:
        rows = await session.execute(
            AfterSale.__table__.select().where(
                AfterSale.order_no == A_SHIPPED, AfterSale.status == "pending"
            )
        )
        assert len(rows.all()) == 1


async def test_create_after_sale_other_user_order_forbidden(auth_client: AsyncClient) -> None:
    response = await auth_client.post(
        "/api/v1/after-sales", json={"orderNo": B_ORDER, "type": "return"}
    )
    assert response.status_code == 403
    assert response.json()["code"] == 2003


async def test_create_after_sale_ineligible_returns_1001(auth_client: AsyncClient) -> None:
    """已关闭订单不能售后：400 而不是 500，且提示是给人看的一句话。"""
    response = await auth_client.post(
        "/api/v1/after-sales", json={"orderNo": A_CLOSED, "type": "return"}
    )
    assert response.status_code == 400
    body = response.json()
    assert body["code"] == 1001
    assert "关闭" in body["message"]


async def test_create_after_sale_unknown_order_forbidden(auth_client: AsyncClient) -> None:
    """不存在的订单与越权同码，防订单号探测。"""
    response = await auth_client.post(
        "/api/v1/after-sales", json={"orderNo": "20990101999", "type": "return"}
    )
    assert response.status_code == 403
    assert response.json()["code"] == 2003


async def test_list_my_after_sales(auth_client: AsyncClient) -> None:
    created = await auth_client.post(
        "/api/v1/after-sales", json={"orderNo": A_SHIPPED, "type": "repair"}
    )
    _created_tickets.append(created.json()["data"]["ticketNo"])

    response = await auth_client.get("/api/v1/after-sales")
    assert response.status_code == 200
    tickets = response.json()["data"]
    assert any(item["ticketNo"] == created.json()["data"]["ticketNo"] for item in tickets)
    assert all(item["type"] in {"return", "exchange", "repair"} for item in tickets)


async def test_handoff_requires_existing_session(auth_client: AsyncClient) -> None:
    response = await auth_client.post(
        "/api/v1/handoff", json={"sessionId": "00000000-0000-0000-0000-000000000000"}
    )
    assert response.status_code == 404
    assert response.json()["code"] == 2004


async def test_handoff_created_and_idempotent(auth_client: AsyncClient) -> None:
    session = await auth_client.post("/api/v1/sessions", json={})
    session_id = session.json()["data"]["id"]

    first = await auth_client.post("/api/v1/handoff", json={"sessionId": session_id})
    second = await auth_client.post("/api/v1/handoff", json={"sessionId": session_id})
    assert first.status_code == 201 and second.status_code == 201
    a = first.json()["data"]
    b = second.json()["data"]
    _created_handoffs.append(a["ticketNo"])
    assert a["ticketNo"].startswith("HO")
    assert a["ticketNo"] == b["ticketNo"]
    assert b["created"] is False

    await auth_client.delete(f"/api/v1/sessions/{session_id}")


async def test_handoff_transition_rejects_rollback(auth_client: AsyncClient) -> None:
    session = await auth_client.post("/api/v1/sessions", json={})
    session_id = session.json()["data"]["id"]
    ticket_no = (await auth_client.post("/api/v1/handoff", json={"sessionId": session_id})).json()[
        "data"
    ]["ticketNo"]
    _created_handoffs.append(ticket_no)

    accepted = await auth_client.patch(f"/api/v1/handoff/{ticket_no}", json={"status": "accepted"})
    assert accepted.status_code == 200
    assert accepted.json()["data"]["status"] == "accepted"

    # accepted → accepted 不是合法流转（状态机不允许原地跳）
    again = await auth_client.patch(f"/api/v1/handoff/{ticket_no}", json={"status": "accepted"})
    assert again.status_code == 400
    assert again.json()["code"] == 1001

    closed = await auth_client.patch(f"/api/v1/handoff/{ticket_no}", json={"status": "closed"})
    assert closed.status_code == 200
    assert closed.json()["data"]["statusLabel"] == "已结束"

    # 已结束的不能再接入
    reopen = await auth_client.patch(f"/api/v1/handoff/{ticket_no}", json={"status": "accepted"})
    assert reopen.status_code == 400

    await auth_client.delete(f"/api/v1/sessions/{session_id}")

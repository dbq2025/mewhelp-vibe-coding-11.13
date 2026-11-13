"""售后多轮链路测试（P3 验收第 4 条的核心用例）。

一条真实的多轮路径：
    1. "我要退货 订单X"        → 不建单，只返回待确认卡片 + 订单摘要
    2. "确认提交"              → 建单，返回工单号
    3. "确认提交"（重复）      → 命中幂等，返回同一张单，**不新建**
    4. "算了不要了"（已建单）  → 如实说撤不回，引导转人工，不谎称已取消

另测两条负向：缺订单号走追问、用户点"先不申请"时不建单。

LLM 一律 Fake（agent.md §9）：这里验证的是图的编排与落库，不是模型质量。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from sqlalchemy import delete, select

from app.agent.llm import set_llm_client
from app.agent.runner import run_turn
from app.domain.services import sessions as session_service
from app.infra.db.models.chat import ChatSession, Message
from app.infra.db.models.order import AfterSale
from app.infra.db.models.user import User
from app.infra.db.session import SessionFactory
from tests.fakes.fake_llm import FakeLlm

A_SHIPPED = "20261101008"


def plan(intent: str, *, confidence: float = 0.9, slots: dict[str, Any] | None = None) -> dict:
    return {"intent": intent, "confidence": confidence, "slots": slots or {}, "tool_plan": []}


class Harness:
    """一轮一轮地跑，自己维护 slots（模拟 runner 的真实调用方式）。"""

    def __init__(self, user: User, chat_id: Any, slots: dict[str, Any]) -> None:
        self.user = user
        self.chat_id = chat_id
        self.slots = slots

    async def say(self, text: str, *, llm_plan: dict) -> tuple[str, list[dict[str, Any]]]:
        async with SessionFactory() as session:
            assistant = Message(
                session_id=self.chat_id, role="assistant", content="", status="incomplete"
            )
            session.add(assistant)
            await session.commit()
            await session.refresh(assistant)
            assistant_id = assistant.id
            history = await session_service.load_history(session, session_id=self.chat_id)

        set_llm_client(FakeLlm(plans=[llm_plan], answers=["（此路径不调生成模型）"]))
        events: list[dict[str, Any]] = []
        async for event in run_turn(
            chat_id=self.chat_id,
            user=self.user,
            user_text=text,
            history=history,
            slots=self.slots,
            assistant_id=assistant_id,
            trace_id="test-p3",
        ):
            events.append(event)

        async with SessionFactory() as session:
            state = await session_service.get_state(session, session_id=self.chat_id)
            self.slots = dict(state.slots or {})
            message = await session.get(Message, assistant_id)
        assert message is not None
        return message.content, events


@pytest.fixture
async def harness() -> AsyncIterator[Harness]:
    async with SessionFactory() as session:
        user = await session.scalar(select(User).where(User.phone == "13800000001"))
        assert user is not None
        chat = await session_service.create_session(session, user_id=user.id)
        state = await session_service.get_state(session, session_id=chat.id)
        slots = dict(state.slots or {})
        chat_id = chat.id

    item = Harness(user=user, chat_id=chat_id, slots=slots)
    yield item

    async with SessionFactory() as session:
        await session.execute(delete(AfterSale).where(AfterSale.source == "agent"))
        await session.execute(delete(Message).where(Message.session_id == chat_id))
        await session.execute(delete(ChatSession).where(ChatSession.id == chat_id))
        await session.commit()


def actions(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [event["action"] for event in events if event.get("type") == "action"]


async def test_missing_order_asks_for_order_no(harness: Harness) -> None:
    reply, events = await harness.say(
        "我要退货", llm_plan=plan("after_sales", slots={"after_sales_type": "return"})
    )
    assert "订单号" in reply
    assert actions(events) == []


async def test_confirm_then_commit_then_idempotent(harness: Harness) -> None:
    # 第 1 轮：只出确认卡片，不建单
    reply, events = await harness.say(
        f"我要退货，订单 {A_SHIPPED}",
        llm_plan=plan("after_sales", slots={"after_sales_type": "return"}),
    )
    assert "确认提交" in reply
    cards = actions(events)
    assert cards and cards[0]["kind"] == "after_sales_confirm"
    assert A_SHIPPED in cards[0]["summary"]

    async with SessionFactory() as session:
        count = len(
            (await session.scalars(select(AfterSale).where(AfterSale.order_no == A_SHIPPED))).all()
        )
    assert count == 0, "待确认阶段不能建单"

    # 第 2 轮：确认 → 建单
    reply, events = await harness.say("确认提交", llm_plan=plan("after_sales", confidence=0.3))
    done = actions(events)
    assert done and done[0]["kind"] == "after_sales_done"
    ticket_no = done[0]["ticketNo"]
    assert ticket_no in reply
    assert done[0]["created"] is True

    # 第 3 轮：再确认一次 → 同一张单，不新建
    reply, events = await harness.say("确认提交", llm_plan=plan("after_sales", confidence=0.3))
    again = actions(events)
    assert again and again[0]["kind"] == "after_sales_done"
    assert again[0]["ticketNo"] == ticket_no
    assert again[0]["created"] is False
    assert "已经在" in reply or "有一张" in reply

    async with SessionFactory() as session:
        rows = list(
            (await session.scalars(select(AfterSale).where(AfterSale.order_no == A_SHIPPED))).all()
        )
    assert len(rows) == 1


async def test_cancel_does_not_create_ticket(harness: Harness) -> None:
    await harness.say(
        f"我要换货，订单 {A_SHIPPED}",
        llm_plan=plan("after_sales", slots={"after_sales_type": "exchange"}),
    )
    reply, events = await harness.say("先不申请", llm_plan=plan("after_sales", confidence=0.3))
    assert "不提交" in reply
    assert actions(events) == []

    async with SessionFactory() as session:
        rows = list(
            (await session.scalars(select(AfterSale).where(AfterSale.order_no == A_SHIPPED))).all()
        )
    assert rows == []


async def test_revoke_after_commit_is_honest(harness: Harness) -> None:
    """已建单后说"算了"：不能谎称已取消，必须说明要找人工撤销。"""
    await harness.say(
        f"我要退货，订单 {A_SHIPPED}",
        llm_plan=plan("after_sales", slots={"after_sales_type": "return"}),
    )
    await harness.say("确认提交", llm_plan=plan("after_sales", confidence=0.3))

    reply, _ = await harness.say("算了不要了", llm_plan=plan("after_sales", confidence=0.3))
    assert "已经提交" in reply
    assert "撤回" in reply or "撤销" in reply

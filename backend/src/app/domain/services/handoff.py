"""转人工工单：幂等建单 + 状态机。

状态机（计划 6.5，坐下端不在本期范围，但状态流转必须可审计）：

    pending ──accept──> accepted ──close──> closed
       └──────────────close/reject──────> closed

规则：
- 同一会话同时只能有一张未完结单（部分唯一索引兜底）。用户连点三下"转人工"不该开三张。
- 状态回退一律拒绝：`closed` 不能再变 `accepted`，否则工单统计和客服工作量都失真。
- 会话上的 `session_states.handoff_status` 跟着同步，前端据此显示"客服已接入"。
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import InvalidParamError
from app.core.logging import get_logger
from app.infra.db.models.ops import HandoffTicket

logger = get_logger(__name__)

STATUS_LABELS = {
    "pending": "排队中",
    "accepted": "已接入",
    "closed": "已结束",
}
OPEN_STATUSES = ("pending", "accepted")

# 允许的流转：目标状态 → 允许的来源状态
TRANSITIONS: dict[str, tuple[str, ...]] = {
    "accepted": ("pending",),
    "closed": ("pending", "accepted"),
}


async def next_ticket_no(session: AsyncSession) -> str:
    seq = await session.scalar(text("select nextval('handoff_ticket_seq')"))
    stamp = datetime.now(UTC).strftime("%Y%m%d")
    return f"HO{stamp}{int(seq or 1) % 10000:04d}"


async def find_open(session: AsyncSession, session_id: object) -> HandoffTicket | None:
    ticket: HandoffTicket | None = await session.scalar(
        select(HandoffTicket).where(
            HandoffTicket.session_id == session_id,
            HandoffTicket.status.in_(OPEN_STATUSES),
        )
    )
    return ticket


async def create_ticket(
    session: AsyncSession,
    *,
    session_id: object,
    user_id: int | None,
    reason: str = "",
) -> tuple[HandoffTicket, bool]:
    """建单。返回 (工单, 是否新建)。同一会话已有未完结单时直接返回那张。"""
    existing = await find_open(session, session_id)
    if existing is not None:
        return existing, False

    ticket = HandoffTicket(
        ticket_no=await next_ticket_no(session),
        session_id=session_id,
        user_id=user_id,
        reason=(reason or "")[:200],
        status="pending",
    )
    session.add(ticket)
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        again = await find_open(session, session_id)
        if again is not None:
            return again, False
        raise
    await session.refresh(ticket)
    logger.info("handoff_created", ticket_no=ticket.ticket_no, reason=ticket.reason)
    return ticket, True


async def get_by_no(session: AsyncSession, ticket_no: str) -> HandoffTicket | None:
    ticket: HandoffTicket | None = await session.scalar(
        select(HandoffTicket).where(HandoffTicket.ticket_no == ticket_no)
    )
    return ticket


async def transition(
    session: AsyncSession, *, ticket: HandoffTicket, to_status: str
) -> HandoffTicket:
    """状态流转。非法流转抛 1001（可预期错误），不做静默忽略。"""
    if to_status not in TRANSITIONS:
        raise InvalidParamError(f"不支持的目标状态：{to_status}")
    allowed = TRANSITIONS[to_status]
    if ticket.status not in allowed:
        raise InvalidParamError(
            f"工单当前是「{STATUS_LABELS.get(ticket.status, ticket.status)}」，"
            f"不能再改为「{STATUS_LABELS.get(to_status, to_status)}」"
        )
    ticket.status = to_status
    await session.commit()
    await session.refresh(ticket)
    logger.info("handoff_transitioned", ticket_no=ticket.ticket_no, to=to_status)
    return ticket

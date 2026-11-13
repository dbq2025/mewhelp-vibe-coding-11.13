"""会话与会话状态服务。

真源约定（计划 3.3）：
- `sessions` / `messages` 是对话内容的唯一真源；
- `session_states.slots` 是槽位的唯一真源；
- **不引入第三份状态**（无 checkpointer），每轮从这两处重建。

软删（`status='deleted'`）而不是物理删：P4 要做会话质量分析，
真删会让"删完就查不到坏案例"变成审计黑洞。
"""

from __future__ import annotations

import base64
import binascii
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import InvalidParamError, NotFoundError
from app.infra.db.models.chat import ChatSession, Message, SessionState

DEFAULT_TITLE = "新会话"
TITLE_MAX = 30


def _encode_cursor(session: ChatSession) -> str:
    raw = f"{session.updated_at.isoformat()}|{session.id}".encode()
    return base64.urlsafe_b64encode(raw).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, UUID]:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        ts, session_id = raw.rsplit("|", 1)
        return datetime.fromisoformat(ts), UUID(session_id)
    except (binascii.Error, UnicodeDecodeError, ValueError) as exc:
        raise InvalidParamError("cursor 不合法") from exc


def title_from_text(text: str) -> str:
    """用首条用户消息生成标题：去掉换行、截断，空则用默认值。"""
    cleaned = " ".join((text or "").split())
    if not cleaned:
        return DEFAULT_TITLE
    return cleaned[:TITLE_MAX] + ("…" if len(cleaned) > TITLE_MAX else "")


async def create_session(
    session: AsyncSession, *, user_id: int, title: str | None = None
) -> ChatSession:
    chat = ChatSession(user_id=user_id, title=(title or DEFAULT_TITLE)[:100])
    session.add(chat)
    await session.flush()
    session.add(SessionState(session_id=chat.id, slots={}, turn_count=0))
    await session.commit()
    await session.refresh(chat)
    return chat


async def get_owned_session(
    session: AsyncSession, *, session_id: UUID, user_id: int
) -> ChatSession:
    """取本人会话。不存在与不属于本人返回同一错误，避免会话 id 探测。"""
    chat = await session.scalar(
        select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.user_id == user_id,
            ChatSession.status != "deleted",
        )
    )
    if chat is None:
        raise NotFoundError("会话不存在")
    return chat


async def list_sessions(
    session: AsyncSession, *, user_id: int, limit: int = 20, cursor: str | None = None
) -> tuple[list[ChatSession], str | None, bool]:
    limit = max(1, min(limit, 50))
    stmt = (
        select(ChatSession)
        .where(ChatSession.user_id == user_id, ChatSession.status != "deleted")
        .order_by(ChatSession.updated_at.desc(), ChatSession.id.desc())
        .limit(limit + 1)
    )
    if cursor:
        ts, last_id = _decode_cursor(cursor)
        stmt = stmt.where(
            (ChatSession.updated_at < ts)
            | ((ChatSession.updated_at == ts) & (ChatSession.id < last_id))
        )
    rows = list((await session.scalars(stmt)).all())
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = _encode_cursor(rows[-1]) if has_more and rows else None
    return rows, next_cursor, has_more


async def rename_session(
    session: AsyncSession, *, session_id: UUID, user_id: int, title: str
) -> ChatSession:
    chat = await get_owned_session(session, session_id=session_id, user_id=user_id)
    chat.title = title.strip()[:100] or DEFAULT_TITLE
    await session.commit()
    await session.refresh(chat)
    return chat


async def soft_delete_session(session: AsyncSession, *, session_id: UUID, user_id: int) -> None:
    chat = await get_owned_session(session, session_id=session_id, user_id=user_id)
    chat.status = "deleted"
    await session.commit()


async def list_messages(
    session: AsyncSession,
    *,
    session_id: UUID,
    limit: int = 50,
    before_id: int | None = None,
) -> tuple[list[Message], bool]:
    """按 id 倒序取一页，返回时翻正序（前端直接渲染）。

    cursor 用 `beforeId` 而不是偏移：消息在头部不断追加，offset 会重复。
    """
    limit = max(1, min(limit, 100))
    stmt = (
        select(Message)
        .where(Message.session_id == session_id, Message.role.in_(("user", "assistant")))
        .order_by(Message.id.desc())
        .limit(limit + 1)
    )
    if before_id:
        stmt = stmt.where(Message.id < before_id)
    rows = list((await session.scalars(stmt)).all())
    has_more = len(rows) > limit
    rows = rows[:limit]
    rows.reverse()
    return rows, has_more


async def get_state(session: AsyncSession, *, session_id: UUID) -> SessionState:
    state = await session.get(SessionState, session_id)
    if state is None:
        # 老会话（P2 之前建的）没有状态行，补一条而不是报错
        state = SessionState(session_id=session_id, slots={}, turn_count=0)
        session.add(state)
        await session.commit()
        await session.refresh(state)
    return state


async def load_history(
    session: AsyncSession, *, session_id: UUID, limit: int = 12
) -> list[dict[str, str]]:
    rows = list(
        (
            await session.scalars(
                select(Message)
                .where(Message.session_id == session_id, Message.status != "blocked")
                .order_by(Message.id.desc())
                .limit(limit)
            )
        ).all()
    )
    rows.reverse()
    return [
        {"role": message.role, "content": message.content}
        for message in rows
        if message.role in ("user", "assistant") and message.content
    ]


async def touch_session(session: AsyncSession, *, chat: ChatSession, user_text: str) -> None:
    """首条消息定标题；每次刷新 updated_at 让侧边栏按最近活跃排序。"""
    if chat.title == DEFAULT_TITLE:
        chat.title = title_from_text(user_text)
    # 用应用时间而不是 func.now()：赋值后还要读回该字段（响应里带 updatedAt），
    # 挂个 SQL 表达式会让属性在 refresh 前不可读
    chat.updated_at = datetime.now(UTC)
    await session.commit()


async def save_turn_state(
    session: AsyncSession,
    *,
    session_id: UUID,
    slots: dict[str, Any],
    intent: str | None,
) -> None:
    state = await get_state(session, session_id=session_id)
    state.slots = slots
    state.last_intent = intent
    state.turn_count = int(state.turn_count or 0) + 1
    await session.commit()


async def count_messages(session: AsyncSession, session_id: UUID) -> int:
    return int(
        await session.scalar(
            select(func.count()).select_from(Message).where(Message.session_id == session_id)
        )
        or 0
    )

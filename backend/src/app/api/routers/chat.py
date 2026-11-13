"""会话 CRUD + 对话 SSE 端点。

SSE 七事件（计划 4.6）：meta / tool / delta / citation / slots / done / error。
HTTP 状态在流开始后不可改，所以**所有能提前判定的失败**（未登录、会话不属于本人、
同会话并发、参数非法）都在返回 StreamingResponse 之前抛出，让前端拿到正常的 4xx envelope；
流内部再出问题只能推 `error` 事件，HTTP 仍是 200。
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator, AsyncIterator
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.agent import concurrency
from app.agent.runner import run_turn
from app.api.deps import CurrentUser
from app.api.schemas.chat import (
    ChatStreamIn,
    MessageOut,
    SessionCreateIn,
    SessionOut,
    SessionPatchIn,
)
from app.api.schemas.common import ApiResponse, PageData, PageMeta, ok
from app.core.config import get_settings
from app.core.deps import DbSession
from app.core.errors import InvalidParamError, SessionBusyError
from app.core.logging import get_logger
from app.core.trace import get_trace_id
from app.domain.services import sessions as session_service
from app.infra.db.models.chat import ChatSession, Message

logger = get_logger(__name__)
router = APIRouter(tags=["chat"])


def _session_out(chat: ChatSession) -> SessionOut:
    return SessionOut(
        id=chat.id,
        title=chat.title,
        createdAt=chat.created_at,
        updatedAt=chat.updated_at,
    )


def _message_out(message: Message) -> MessageOut:
    return MessageOut(
        id=message.id,
        role=message.role,  # type: ignore[arg-type]
        content=message.content,
        status=message.status,
        intent=message.intent,
        citations=message.citations or [],
        tools=message.tool_calls or [],
        latencyMs=message.latency_ms,
        createdAt=message.created_at,
    )


# ------------------------------------------------------------------ 会话 CRUD
@router.get("/sessions", response_model=ApiResponse[PageData[SessionOut]], summary="会话列表")
async def list_sessions(
    session: DbSession,
    user: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    cursor: Annotated[str | None, Query()] = None,
) -> ApiResponse[PageData[SessionOut]]:
    rows, next_cursor, has_more = await session_service.list_sessions(
        session, user_id=user.id, limit=limit, cursor=cursor
    )
    return ok(
        PageData[SessionOut](
            items=[_session_out(row) for row in rows],
            page=PageMeta(nextCursor=next_cursor, hasMore=has_more),
        )
    )


@router.post(
    "/sessions",
    response_model=ApiResponse[SessionOut],
    status_code=201,
    summary="新建会话",
)
async def create_session(
    session: DbSession,
    user: CurrentUser,
    payload: SessionCreateIn | None = None,
) -> ApiResponse[SessionOut]:
    chat = await session_service.create_session(
        session, user_id=user.id, title=(payload.title if payload else None)
    )
    return ok(_session_out(chat))


@router.patch("/sessions/{session_id}", response_model=ApiResponse[SessionOut], summary="重命名")
async def rename_session(
    session_id: UUID,
    payload: SessionPatchIn,
    session: DbSession,
    user: CurrentUser,
) -> ApiResponse[SessionOut]:
    chat = await session_service.rename_session(
        session, session_id=session_id, user_id=user.id, title=payload.title
    )
    return ok(_session_out(chat))


@router.delete("/sessions/{session_id}", response_model=ApiResponse[None], summary="删除会话")
async def delete_session(
    session_id: UUID,
    session: DbSession,
    user: CurrentUser,
) -> ApiResponse[None]:
    await session_service.soft_delete_session(session, session_id=session_id, user_id=user.id)
    return ok(None, "已删除")


@router.get(
    "/sessions/{session_id}/messages",
    response_model=ApiResponse[PageData[MessageOut]],
    summary="历史消息",
)
async def list_messages(
    session_id: UUID,
    session: DbSession,
    user: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    beforeId: Annotated[int | None, Query(alias="beforeId")] = None,
) -> ApiResponse[PageData[MessageOut]]:
    await session_service.get_owned_session(session, session_id=session_id, user_id=user.id)
    rows, has_more = await session_service.list_messages(
        session, session_id=session_id, limit=limit, before_id=beforeId
    )
    return ok(
        PageData[MessageOut](
            items=[_message_out(row) for row in rows],
            page=PageMeta(hasMore=has_more),
        )
    )


# ------------------------------------------------------------------ 对话
@router.post("/chat/stream", summary="流式对话（SSE）")
async def chat_stream(
    payload: ChatStreamIn,
    request: Request,
    session: DbSession,
    user: CurrentUser,
) -> Response:
    settings = get_settings()
    trace_id = get_trace_id()
    chat = await session_service.get_owned_session(
        session, session_id=payload.sessionId, user_id=user.id
    )
    user_text = payload.message.strip()
    if not user_text:
        raise InvalidParamError("消息不能为空")

    # 幂等：同一个 clientMsgId 直接重放上次结果，不重复调模型、不重复落库
    if payload.clientMsgId:
        replay = await _find_replay(session, chat.id, payload.clientMsgId)
        if replay is not None:
            return _replay_response(replay)

    if not await concurrency.acquire(str(chat.id), wait_seconds=settings.session_lock_wait_seconds):
        raise SessionBusyError()

    try:
        state = await session_service.get_state(session, session_id=chat.id)
        slots = dict(state.slots or {})
        # 历史必须在插入本轮用户消息之前取，否则同一句话会同时出现在 history 与当前输入里
        history = await session_service.load_history(session, session_id=chat.id, limit=12)

        session.add(
            Message(
                session_id=chat.id,
                role="user",
                content=user_text,
                client_msg_id=payload.clientMsgId,
                trace_id=trace_id,
            )
        )
        await session.commit()

        assistant = Message(
            session_id=chat.id,
            role="assistant",
            content="",
            status="incomplete",
            trace_id=trace_id,
        )
        session.add(assistant)
        await session.commit()
        await session.refresh(assistant)

        await session_service.touch_session(session, chat=chat, user_text=user_text)
    except Exception:
        concurrency.release(str(chat.id))
        raise

    events = run_turn(
        chat_id=chat.id,
        user=user,
        user_text=user_text,
        history=history,
        slots=slots,
        assistant_id=assistant.id,
        trace_id=trace_id,
        lock_held=True,
    )

    return StreamingResponse(
        _sse(events, request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
            "X-Trace-Id": trace_id,
        },
    )


async def _sse(events: AsyncGenerator[dict[str, Any]], request: Request) -> AsyncIterator[bytes]:
    """把事件字典序列化成 SSE 帧。客户端断开时停止迭代（由 runner 落 incomplete）。"""
    try:
        async for event in events:
            if await request.is_disconnected():
                logger.info("sse_client_disconnected")
                break
            payload = json.dumps(event, ensure_ascii=False, default=str)
            yield f"event: {event.get('type', 'message')}\ndata: {payload}\n\n".encode()
    finally:
        # 关闭生成器，触发 runner 的 finally（落库 + 释放锁）
        await events.aclose()


async def _find_replay(session: DbSession, session_id: UUID, client_msg_id: str) -> Message | None:
    user_msg = await session.scalar(
        select(Message).where(
            Message.session_id == session_id, Message.client_msg_id == client_msg_id
        )
    )
    if user_msg is None:
        return None
    assistant = await session.scalar(
        select(Message)
        .where(
            Message.session_id == session_id,
            Message.role == "assistant",
            Message.id > user_msg.id,
        )
        .order_by(Message.id)
        .limit(1)
    )
    return assistant


def _replay_response(message: Message) -> StreamingResponse:
    async def _events() -> AsyncIterator[dict[str, Any]]:
        yield {
            "type": "meta",
            "messageId": message.id,
            "intent": message.intent or "replay",
            "confidence": 1.0,
            "replayed": True,
        }
        yield {"type": "delta", "text": message.content or ""}
        for citation in message.citations or []:
            yield {"type": "citation", **citation}
        yield {
            "type": "done",
            "messageId": message.id,
            "usage": {"prompt": message.prompt_tokens, "completion": message.completion_tokens},
            "latencyMs": message.latency_ms or 0,
            "status": message.status,
        }

    async def _frames() -> AsyncIterator[bytes]:
        async for event in _events():
            yield (
                f"event: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
            ).encode()

    return StreamingResponse(
        _frames(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )

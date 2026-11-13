"""一轮对话的执行器：把图、SSE 事件、落库串起来。

关键设计：**执行器自己持有 DB 会话**，不复用请求级会话。
原因：用户点"停止"时 FastAPI 会取消响应生成器，请求级会话可能已经在关闭流程里，
在 `finally` 里再拿它写库会写到一半被掐断。独立会话 + `asyncio.shield` 能保证
"内容不完整也要落库"，前端才能显示 `incomplete` 并允许重试。
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncGenerator
from typing import Any, cast
from uuid import UUID

from app.agent import concurrency
from app.agent.graph import get_graph
from app.agent.runtime import RunContext, use_context
from app.agent.state import GraphState
from app.core.logging import get_logger
from app.domain.services import sessions as session_service
from app.infra.db.models.chat import Message
from app.infra.db.models.ops import LlmUsage
from app.infra.db.models.user import User
from app.infra.db.session import SessionFactory

logger = get_logger(__name__)


async def run_turn(
    *,
    chat_id: UUID,
    user: User,
    user_text: str,
    history: list[dict[str, str]],
    slots: dict[str, Any],
    assistant_id: int,
    trace_id: str,
    lock_held: bool = True,
) -> AsyncGenerator[dict[str, Any]]:
    """产出 SSE 事件字典；结束时把助手消息与会话状态写入库。"""
    started = time.perf_counter()
    final: dict[str, Any] = {}
    status = "incomplete"
    citations: list[dict[str, Any]] = []
    usage = {"prompt": 0, "completion": 0}
    llm_calls: list[dict[str, Any]] = []
    text_parts: list[str] = []
    error_code: int | None = None
    emitted_error = False

    initial: GraphState = {
        "session_id": str(chat_id),
        "user_id": user.id,
        "user_text": user_text,
        "history": history,
        "slots": slots,
        "message_id": assistant_id,
    }

    try:
        async with SessionFactory() as db:
            ctx = RunContext(
                session=db,
                session_id=str(chat_id),
                trace_id=trace_id,
                user=user,
            )
            with use_context(ctx):
                llm_calls = ctx.llm_calls
                # stream_mode 传列表时，LangGraph 逐条产出 (mode, payload) 二元组；
                # 类型标注在 v1/v2 之间有差异，这里显式 cast 收窄，避免 Any 泄漏到业务代码
                stream = get_graph().astream(initial, stream_mode=["custom", "values"])
                async for item in stream:
                    mode, payload = cast("tuple[str, Any]", item)
                    if mode == "custom":
                        event: dict[str, Any] = payload
                        if event.get("type") == "delta":
                            text_parts.append(event.get("text", ""))
                        elif event.get("type") == "error":
                            error_code = int(event.get("code") or 5000)
                            emitted_error = True
                        yield event
                    else:
                        final = cast("dict[str, Any]", payload)

            citations = list(final.get("citations") or ctx.citations or [])
            usage = {
                "prompt": int(final.get("prompt_tokens") or 0),
                "completion": int(final.get("completion_tokens") or 0),
            }
            status = "blocked" if final.get("blocked") else "ok"
    except asyncio.CancelledError:
        # 用户点停止：保留已生成内容，标 incomplete，交给前端"重试本条"
        status = "incomplete"
        raise
    except Exception as exc:
        logger.exception("agent_turn_failed", error=repr(exc))
        status = "incomplete"
        error_code = error_code or 5000
        fallback = "抱歉，这一轮处理出了问题。你可以重试一次，或者我帮你转人工客服。"
        text_parts.append(fallback)
        yield {"type": "delta", "text": fallback}
        yield {
            "type": "error",
            "code": 5000,
            "message": "服务处理异常，已保留本次会话",
            "retryable": True,
        }
    finally:
        latency_ms = int((time.perf_counter() - started) * 1000)
        draft = "".join(text_parts).strip()
        await _persist_safely(
            chat_id=chat_id,
            assistant_id=assistant_id,
            content=draft,
            status=status,
            intent=str(final.get("intent") or "") or None,
            citations=citations,
            tool_trace=final.get("tool_trace") or [],
            slots=final.get("slots") or slots,
            usage=usage,
            llm_calls=llm_calls,
            latency_ms=latency_ms,
            trace_id=trace_id,
        )
        if lock_held:
            concurrency.release(str(chat_id))

    for citation in citations:
        yield {"type": "citation", **citation}
    if error_code is not None and not emitted_error:
        yield {
            "type": "error",
            "code": error_code,
            "message": "回答可能不完整，可重试",
            "retryable": True,
        }
    yield {
        "type": "done",
        "messageId": assistant_id,
        "usage": usage,
        "latencyMs": int((time.perf_counter() - started) * 1000),
        "status": status,
    }


async def _persist_safely(**kwargs: Any) -> None:
    """落库必须独立于请求生命周期：shield 保证即使外部取消也写完整条消息。"""
    task = asyncio.create_task(_persist(**kwargs))
    try:
        await asyncio.shield(task)
    except asyncio.CancelledError:
        logger.warning("persist_cancelled", message_id=kwargs.get("assistant_id"))
    except Exception as exc:
        logger.error("persist_failed", error=repr(exc), message_id=kwargs.get("assistant_id"))


async def _persist(
    *,
    chat_id: UUID,
    assistant_id: int,
    content: str,
    status: str,
    intent: str | None,
    citations: list[dict[str, Any]],
    tool_trace: list[dict[str, Any]],
    slots: dict[str, Any],
    usage: dict[str, int],
    llm_calls: list[dict[str, Any]],
    latency_ms: int,
    trace_id: str,
) -> None:
    async with SessionFactory() as db:
        message = await db.get(Message, assistant_id)
        if message is None:
            logger.error("assistant_message_missing", message_id=assistant_id)
            return
        message.content = content
        message.status = status
        message.intent = intent
        message.citations = citations or None
        message.tool_calls = tool_trace or None
        message.prompt_tokens = usage.get("prompt", 0)
        message.completion_tokens = usage.get("completion", 0)
        message.latency_ms = latency_ms
        message.trace_id = trace_id
        # 计量与消息同一个事务：要么都落、要么都不落，不会出现"有消息没成本"的账
        for call in llm_calls:
            db.add(
                LlmUsage(
                    trace_id=trace_id,
                    session_id=chat_id,
                    model=str(call.get("model") or ""),
                    prompt_tokens=int(call.get("prompt_tokens") or 0),
                    completion_tokens=int(call.get("completion_tokens") or 0),
                    latency_ms=int(call.get("latency_ms") or 0),
                    ok=bool(call.get("ok", True)),
                    error_code=call.get("error_code"),
                )
            )
        await db.commit()

        await session_service.save_turn_state(db, session_id=chat_id, slots=slots, intent=intent)

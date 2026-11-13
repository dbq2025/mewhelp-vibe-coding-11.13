"""一次问询的运行上下文。

为什么用 ContextVar 而不是 LangGraph 的 configurable：图里每个节点都要拿 DB 会话、
当前用户、trace_id，走 configurable 需要往 config 里塞不可序列化对象，
新版 LangGraph 在 tracing/序列化上会报难懂的错。ContextVar 更直白：

    with use_context(ctx):
        async for chunk in graph.astream(state, stream_mode=["custom", "values"]):
            ...

节点里 `get_context()` 就能拿到会话，不用层层传参。
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from langgraph.config import get_stream_writer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.infra.db.models.user import User

logger = get_logger(__name__)


@dataclass
class RunContext:
    session: AsyncSession
    session_id: str
    trace_id: str
    user: User | None = None
    # 本轮被授权访问的订单号（输出校验时保留，其余一律改写）
    allowed_order_nos: set[str] = field(default_factory=set)
    citations: list[dict[str, Any]] = field(default_factory=list)


_ctx: ContextVar[RunContext | None] = ContextVar("agent_run_context", default=None)


@contextmanager
def use_context(ctx: RunContext) -> Any:
    token = _ctx.set(ctx)
    try:
        yield ctx
    finally:
        _ctx.reset(token)


def get_context() -> RunContext:
    ctx = _ctx.get()
    if ctx is None:
        raise RuntimeError("Agent 运行上下文未初始化（只能在 runner 内调用）")
    return ctx


def emit(event: dict[str, Any]) -> None:
    """向 SSE 推送一个事件。非流式调用（单测直接跑节点）时静默丢弃。"""
    try:
        writer = get_stream_writer()
    except Exception:
        return
    try:
        writer(event)
    except Exception:
        logger.debug("sse_emit_dropped", event_type=event.get("type"))

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
    # 本轮已执行的工具数：超过 settings.max_tool_steps 就地降级，
    # 而不是让图继续往下走（防"工具链越跑越长"和死循环）
    tool_steps: int = 0
    # 本轮每一次模型调用的计量，由 runner 统一落 llm_usage 表。
    # 为什么不直接在 llm.py 里写库：LLM 客户端不该知道数据库长什么样，
    # 而且一轮里有多次调用（理解 + 生成 + 重试），集中落库才能保证同一事务。
    llm_calls: list[dict[str, Any]] = field(default_factory=list)


_ctx: ContextVar[RunContext | None] = ContextVar("agent_run_context", default=None)


def record_llm_call(
    *,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    latency_ms: int,
    ok: bool,
    error_code: int | None = None,
) -> None:
    """记录一次模型调用。没有运行上下文时静默丢弃（单测直接跑节点、脚本预热等场景）。"""
    ctx = _ctx.get()
    if ctx is None:
        return
    ctx.llm_calls.append(
        {
            "model": model,
            "prompt_tokens": max(0, prompt_tokens),
            "completion_tokens": max(0, completion_tokens),
            "latency_ms": max(0, latency_ms),
            "ok": ok,
            "error_code": None if error_code is None else str(error_code),
        }
    )


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

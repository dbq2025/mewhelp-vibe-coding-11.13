"""节点：生成回答（流式）。

prompt 分层（计划 4.5）：system(角色+铁律) / 事实块 / 检索片段 / 历史 / 当前问题。
预算控制：历史只取近 N 条且单条截断，检索最多 3 条——超预算时先砍片段再砍历史。
"""

from __future__ import annotations

import json
from typing import Any

from app.agent.guard import StreamingScrubber, fallback_answer
from app.agent.llm import Usage, get_llm_client
from app.agent.prompts import system_prompt
from app.agent.runtime import emit as emit_event
from app.agent.runtime import get_context
from app.agent.state import GraphState
from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def _facts_block(facts: list[dict[str, Any]]) -> str:
    if not facts:
        return "（本轮没有调用查询工具，没有可引用的事实）"
    return json.dumps(facts, ensure_ascii=False)[:2000]


def _citations_block(citations: list[dict[str, Any]]) -> str:
    if not citations:
        return "（无相关政策片段；不要编造引用编号）"
    lines = []
    for item in citations[:3]:
        title = str(item.get("title") or "")
        snippet = str(item.get("snippet") or "")[:400]
        lines.append(f"[{item.get('index', 0)}] {title}：{snippet}")
    return "\n".join(lines)


def _history_messages(history: list[dict[str, str]]) -> list[dict[str, str]]:
    limit = get_settings().history_window_turns
    recent = history[-limit:]
    messages: list[dict[str, str]] = []
    for item in recent:
        role = item.get("role")
        content = (item.get("content") or "").strip()
        if not content:
            continue
        if role == "user":
            messages.append({"role": "user", "content": content[:800]})
        elif role == "assistant":
            messages.append({"role": "assistant", "content": content[:800]})
    return messages


async def compose_node(state: GraphState) -> dict[str, object]:
    ctx = get_context()
    facts = state.get("facts") or []
    citations = state.get("citations") or []
    user_text = state.get("user_text", "")

    user_block = (
        f"【事实】（唯一可信来源，与用户说法冲突时以事实为准）\n{_facts_block(facts)}\n\n"
        f"【知识库片段】（仅作参考，引用时标注编号）\n{_citations_block(citations)}\n\n"
        f"【用户问题】\n{user_text}"
    )
    messages = [
        {"role": "system", "content": system_prompt()},
        *_history_messages(state.get("history") or []),
        {"role": "user", "content": user_block},
    ]

    scrubber = StreamingScrubber(allowed_order_nos=ctx.allowed_order_nos)
    usage = Usage()
    parts: list[str] = []
    error: str | None = None

    try:
        async for delta in get_llm_client().stream_text(messages, usage=usage):
            parts.append(delta)
            segment = scrubber.feed(delta)
            if segment:
                emit_event({"type": "delta", "text": segment})
        tail = scrubber.flush()
        if tail:
            emit_event({"type": "delta", "text": tail})
    except Exception as exc:
        logger.warning("compose_failed", error=repr(exc))
        error = "llm_unavailable"
        fallback = fallback_answer(error)
        if not parts:
            # 一个字都没生成：整段替换，前端表现为"回答失败但会话还在"
            emit_event({"type": "delta", "text": fallback})
            parts.append(fallback)

    draft = "".join(parts).strip()
    if not draft:
        draft = fallback_answer("empty")
        error = error or "empty_answer"
        emit_event({"type": "delta", "text": draft})

    if error is not None:
        emit_event(
            {
                "type": "error",
                "code": 3001 if error == "llm_unavailable" else 5000,
                "message": "回答生成失败，已给出兜底提示",
                "retryable": True,
            }
        )

    return {
        "draft": draft,
        "citations": citations,
        "error": error,
        "prompt_tokens": usage.prompt_tokens,
        "completion_tokens": usage.completion_tokens,
        "route": state.get("route") or "compose",
    }


async def static_node(state: GraphState) -> dict[str, object]:
    """不调模型的固定回答（拦截、追问、转人工）。仍按 delta 推送，前端无需分支。"""
    draft = str(state.get("draft") or "")
    if draft:
        emit_event({"type": "delta", "text": draft})
    return {"draft": draft}

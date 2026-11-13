"""Agent 图状态与意图枚举。

单一真源（计划 3.3）：图状态每轮从 DB 重建（`session_states.slots` + 近 N 条消息），
**不引入 LangGraph checkpointer**。原因：checkpointer 会与业务 `messages` 表形成双真源，
出问题时无法判断以谁为准；而本项目每轮都要落库，重建成本可以忽略。

意图标签集合只在这里定义一次：prompt、路由、评测集共用，避免"prompt 里写了 8 类、
代码只处理 6 类"这种漂移。
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, TypedDict


class Intent(StrEnum):
    PRODUCT_SEARCH = "product_search"
    PRODUCT_INFO = "product_info"
    ORDER_STATUS = "order_status"
    AFTER_SALES = "after_sales"
    POLICY_FAQ = "policy_faq"
    CHITCHAT = "chitchat"
    HANDOFF = "handoff"


# 兜底意图：模型给出未知标签时按闲聊处理，禁止直接 500
INTENT_FALLBACK = Intent.CHITCHAT

# 需要用户先提供订单号的意图
ORDER_INTENTS = {Intent.ORDER_STATUS, Intent.AFTER_SALES}

# 需要检索知识库的意图（售后流程也要查政策，所以两个都算）
RETRIEVAL_INTENTS = {Intent.POLICY_FAQ, Intent.AFTER_SALES}


class Route(StrEnum):
    CLARIFY = "clarify"
    SALES = "sales_agent"
    ORDER = "order_flow"
    RETRIEVE = "retrieve"
    AFTER_SALES = "after_sales"
    CHITCHAT = "chitchat"
    HANDOFF = "handoff"
    BLOCKED = "blocked"


class ToolCall(TypedDict, total=False):
    name: str
    args: dict[str, Any]
    ok: bool
    summary: str
    error_code: str | None
    latency_ms: int


class GraphState(TypedDict, total=False):
    """一轮对话的完整状态。所有字段可选：节点只返回自己负责的部分。"""

    # 输入
    session_id: str
    message_id: int
    user_id: int
    user_text: str
    history: list[dict[str, str]]
    slots: dict[str, Any]

    # 理解结果
    intent: str
    confidence: float
    low_confidence_streak: int
    clarify_question: str | None
    tool_plan: list[dict[str, Any]]

    # 路由与执行
    route: str
    # 待确认动作的处理结果：commit / cancel / ask（售后二次确认用）
    action: str | None
    facts: list[dict[str, Any]]
    tool_trace: list[ToolCall]
    retrieved: list[dict[str, Any]]
    citations: list[dict[str, Any]]

    # 输出
    draft: str
    blocked: bool
    blocked_reason: str | None
    error: str | None
    prompt_tokens: int
    completion_tokens: int
    slots_changed: bool


def parse_intent(raw: object) -> Intent:
    """把模型输出的标签收敛到枚举，未知标签走兜底（不抛异常打断对话）。"""
    text = str(raw or "").strip().lower()
    for intent in Intent:
        if text == intent.value:
            return intent
    return INTENT_FALLBACK

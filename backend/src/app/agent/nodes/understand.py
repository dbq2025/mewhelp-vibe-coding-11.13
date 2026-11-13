"""节点：意图理解 + 槽位合并 + 路由决策。

一次 LLM 调用同时产出「意图 + 置信度 + 槽位 + 工具计划」。为什么不做多轮 ReAct：
- 首 token 预算 2.5s，多一轮模型往返就吃掉 0.8~1.2s；
- 商品/订单场景的工具依赖是**一层**的（先搜再答），不需要多次观察反馈；
- 少一次模型调用就少一处 JSON 解析失败点。
代价：跨工具的链式推理（"帮我找 A 的替代品再比一下价格"）要等 P3 的 ReAct 循环，
这条已写进 docs/IMPLEMENTATION_PLAN.md 的偏差记录。
"""

from __future__ import annotations

import json
from typing import Any

from app.agent import slots as slot_utils
from app.agent.llm import get_llm_client
from app.agent.prompts import load
from app.agent.runtime import emit
from app.agent.state import (
    INTENT_FALLBACK,
    ORDER_INTENTS,
    RETRIEVAL_INTENTS,
    GraphState,
    Intent,
    Route,
    parse_intent,
)
from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_ALLOWED_TOOLS = {
    "search_products",
    "get_product",
    "compare_products",
    "get_order",
    "get_shipment",
    "search_policy",
}

_CLARIFY_BY_INTENT = {
    Intent.ORDER_STATUS: (
        "你想查哪笔订单？把订单号发我（形如 20261101001），或者告诉我是哪天下单的。"
    ),
    Intent.AFTER_SALES: "这笔订单的订单号是多少？我先帮你确认状态，再说具体怎么处理。",
    Intent.PRODUCT_INFO: "你指的是哪一款商品？说下名字，或者把上一轮我列的序号告诉我也行。",
}


def _history_text(history: list[dict[str, str]], limit: int = 6) -> str:
    recent = history[-limit:]
    lines = []
    for item in recent:
        role = "用户" if item.get("role") == "user" else "客服"
        lines.append(f"{role}：{item.get('content', '')[:200]}")
    return "\n".join(lines) if lines else "（无）"


def _to_confidence(value: Any) -> float:
    """模型偶尔把置信度写成 "0.9" 字符串或 null，这里统一收敛到 [0,1]。"""
    try:
        number = float(str(value))
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(number, 1.0))


def _normalize_price(value: Any) -> int | None:
    """模型有时给元、有时给分。小于等于 5000 的数值按"元"理解（5000 分 = 50 元，不像商品预算）。

    规则抽槽（`slots.extract_rules`）已经做过元→分换算且优先级更高，
    这里只兜模型单独给出的价格。
    """
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    return number * 100 if number <= 5000 else number


def _sanitize_plan(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    plan: list[dict[str, Any]] = []
    for step in raw[:2]:
        if not isinstance(step, dict):
            continue
        name = str(step.get("tool") or "")
        if name not in _ALLOWED_TOOLS:
            continue
        args = step.get("args")
        plan.append({"tool": name, "args": args if isinstance(args, dict) else {}})
    return plan


async def understand_node(state: GraphState) -> dict[str, object]:
    settings = get_settings()
    user_text = state.get("user_text", "")
    current_slots = dict(state.get("slots") or {})

    # 1) 规则先抽：订单号、尾号、价格、指代，确定性部分不交给模型
    rule_slots = slot_utils.extract_rules(user_text, current_slots)

    # 2) 模型理解意图（失败不阻断：降级为低置信 + 追问）
    known = {k: v for k, v in current_slots.items() if not k.startswith("_")}
    known["candidates"] = current_slots.get("last_products") or []
    messages = [
        {"role": "system", "content": load("understand")},
        {
            "role": "user",
            "content": (
                f"【已知槽位】\n{json.dumps(known, ensure_ascii=False)[:1200]}\n\n"
                f"【上轮对话】\n{_history_text(state.get('history') or [])}\n\n"
                f"【用户当前输入】\n{user_text}"
            ),
        },
    ]

    intent = INTENT_FALLBACK
    confidence = 0.0
    llm_slots: dict[str, Any] = {}
    tool_plan: list[dict[str, Any]] = []
    clarify_question: str | None = None
    try:
        data, _ = await get_llm_client().complete_json(messages)
        intent = parse_intent(data.get("intent"))
        confidence = _to_confidence(data.get("confidence"))
        raw_slots = data.get("slots")
        if isinstance(raw_slots, dict):
            llm_slots = raw_slots
        tool_plan = _sanitize_plan(data.get("tool_plan"))
        if data.get("need_clarify") and data.get("clarify_question"):
            clarify_question = str(data["clarify_question"])[:200]
    except Exception as exc:
        logger.warning("understand_failed", error=repr(exc))
        confidence = 0.0

    # 3) 合并槽位：模型给关键词/类目，规则给确定性字段；规则覆盖模型
    merged_slots, changed = slot_utils.merge_slots(current_slots, llm_slots)
    if "price_max" in llm_slots and "price_max" not in rule_slots:
        normalized = _normalize_price(llm_slots.get("price_max"))
        if normalized is not None:
            merged_slots["price_max"] = normalized
    merged_slots, rule_changed = slot_utils.merge_slots(merged_slots, rule_slots)
    changed = sorted(set(changed) | set(rule_changed))

    # 4) 待确认动作：写操作前的二次确认必须走规则，不能交给模型判"用户同意了吗"
    action: str | None = None
    pending = merged_slots.get(slot_utils.PENDING_ACTION)
    if isinstance(pending, dict) and pending.get("kind") == "after_sales":
        verdict = slot_utils.classify_confirmation(user_text)
        if verdict == "confirm":
            action = "commit"
        elif verdict == "deny":
            action = "cancel"
        else:
            # 这轮说了别的（改口类型、问政策、换话题）→ 作废待确认，按新意图走
            merged_slots.pop(slot_utils.PENDING_ACTION, None)
    # 已经建过单的用户又说了句"确认"/"算了"：走幂等或撤销分支，
    # 而不是当成听不懂把他推给人工（实测过：重复确认会让低置信计数直接兜到转人工）
    elif isinstance(merged_slots.get("last_after_sales"), dict):
        verdict = slot_utils.classify_confirmation(user_text)
        if verdict == "confirm":
            action = "commit"
        elif verdict == "deny":
            # 单子已经建了，撤销不是"不提交"，必须走人工，不能谎称已取消
            action = "revoke"

    # 5) 低置信连续计数（存在 slots 的内部键里，不额外加表）
    streak = int(current_slots.get("_low_conf") or 0)
    if confidence < settings.intent_confidence_threshold:
        streak += 1
    else:
        streak = 0
    merged_slots["_low_conf"] = streak

    # 6) 路由
    route, clarify_question = _decide_route(
        intent=intent,
        confidence=confidence,
        slots=merged_slots,
        clarify_question=clarify_question,
        streak=streak,
        tool_plan=tool_plan,
        action=action,
    )

    emit(
        {
            "type": "meta",
            "messageId": state.get("message_id"),
            "intent": intent.value,
            "confidence": round(confidence, 3),
        }
    )
    changes = slot_utils.summarize_changes(changed, merged_slots)
    if changes["changed"]:
        emit({"type": "slots", "slots": changes})

    return {
        "intent": intent.value,
        "confidence": confidence,
        "slots": merged_slots,
        "slots_changed": bool(changes["changed"]),
        "low_confidence_streak": streak,
        "tool_plan": tool_plan,
        "route": route,
        "action": action,
        "clarify_question": clarify_question,
    }


def _decide_route(
    *,
    intent: Intent,
    confidence: float,
    slots: dict[str, Any],
    clarify_question: str | None,
    streak: int,
    tool_plan: list[dict[str, Any]],
    action: str | None = None,
) -> tuple[str, str | None]:
    settings = get_settings()

    # 二次确认的优先级最高：用户只说"确认"，模型给低置信也不该被反问打断
    if action in ("commit", "cancel", "revoke"):
        return Route.AFTER_SALES.value, None

    if confidence < settings.intent_confidence_threshold:
        # 规则已经抽到订单号时，唯一缺的信息其实已经有了，此时再问"哪一笔订单"
        # 就是明知故问（实测：多意图问句里模型只给 0.55 的置信度，用户被反问一次）
        if slots.get("order_no") and intent in ORDER_INTENTS | {Intent.AFTER_SALES}:
            return (
                Route.AFTER_SALES.value if intent == Intent.AFTER_SALES else Route.ORDER.value,
                None,
            )
        if streak >= settings.low_confidence_limit:
            # 连续两次听不懂就别再追问了，直接给人工出口（计划 4.2）
            return Route.HANDOFF.value, None
        question = clarify_question or _CLARIFY_BY_INTENT.get(
            intent,
            "我想确认一下你的问题：是想找商品、查订单，还是咨询退换货这类政策？",
        )
        return Route.CLARIFY.value, question

    if intent == Intent.HANDOFF:
        return Route.HANDOFF.value, None

    if intent == Intent.AFTER_SALES:
        # 售后有独立链路（受理判定 + 二次确认 + 建单），不能混进"只读查询"里
        if slots.get("order_no") or slots.get("last_order_no"):
            return Route.AFTER_SALES.value, None
        return Route.CLARIFY.value, clarify_question or _CLARIFY_BY_INTENT[intent]

    if intent in ORDER_INTENTS:
        if slots.get("order_no"):
            return Route.ORDER.value, None
        # 没有订单号不等于要追问：登录用户可以直接说"我最近那单"
        if not slots.get("order_no") and "我的订单" in str(slots.get("keyword") or ""):
            return Route.ORDER.value, None
        if _plan_targets(tool_plan, {"get_order", "get_shipment"}):
            return Route.ORDER.value, None
        return Route.CLARIFY.value, clarify_question or _CLARIFY_BY_INTENT[intent]

    if intent in RETRIEVAL_INTENTS and intent != Intent.AFTER_SALES:
        return Route.RETRIEVE.value, None

    if intent in (Intent.PRODUCT_SEARCH, Intent.PRODUCT_INFO):
        return Route.SALES.value, None

    return Route.CHITCHAT.value, None


def _plan_targets(plan: list[dict[str, Any]], names: set[str]) -> bool:
    return any(step.get("tool") in names for step in plan)


def route_after_understand(state: GraphState) -> str:
    return str(state.get("route") or Route.CHITCHAT.value)

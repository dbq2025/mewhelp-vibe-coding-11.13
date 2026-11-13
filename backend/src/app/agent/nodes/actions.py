"""节点：业务动作（销售 / 订单 / 政策检索 / 转人工 / 静态回答）。

分工原则（计划 4.2）：
- 商品咨询 → 走工具，让模型基于事实措辞；
- 订单与售后 → **确定性链路**：先鉴权、再取数、再措辞。这类场景失败代价不对称，
  一次幻觉就是一封投诉，所以不给模型"自由编排"的空间。游客查单由 authz 统一拦截。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import tools
from app.agent.runtime import emit, get_context
from app.agent.state import GraphState, Route
from app.agent.tools import ToolResult
from app.core.config import get_settings
from app.core.logging import get_logger
from app.domain.services import handoff as handoff_service
from app.domain.services import orders as order_service
from app.domain.services import sessions as session_service

logger = get_logger(__name__)

_PRODUCT_TOOLS = {"search_products", "get_product", "compare_products"}


async def _run_tool(session: AsyncSession, name: str, args: dict[str, Any]) -> ToolResult:
    """执行单个工具并把 start/end 事件推给前端。工具失败不抛异常，转为事实。

    工具步数上限（计划 P3 验收 3）：超限就地降级成"查不到了"，而不是继续往下跑。
    降级而不是抛异常，是因为模型还有机会用已有事实作答；抛异常会让整轮对话失败。
    """
    ctx = get_context()
    budget = get_settings().max_tool_steps
    if ctx.tool_steps >= budget:
        logger.warning("tool_budget_exceeded", tool=name, steps=ctx.tool_steps)
        emit(
            {
                "type": "tool",
                "name": name,
                "status": "end",
                "ok": False,
                "summary": f"本轮查询已达 {budget} 次上限，先按已有信息回答",
                "latencyMs": 0,
            }
        )
        return ToolResult(
            name,
            False,
            error_code="4008",
            summary=f"本轮查询次数已达上限（{budget} 次），不要继续查，按已有信息如实回答",
        )
    ctx.tool_steps += 1
    emit({"type": "tool", "name": name, "status": "start", "summary": _args_hint(name, args)})
    try:
        if name == "search_products":
            result = await tools.search_products(
                session,
                keyword=_opt_str(args.get("keyword")),
                category=_opt_str(args.get("category")),
                price_min=_opt_int(args.get("price_min")),
                price_max=_opt_int(args.get("price_max")),
                sort=str(args.get("sort") or "recommend"),
                limit=int(args.get("limit") or 5),
            )
        elif name == "get_product":
            product_id = _opt_int(args.get("product_id"))
            result = (
                await tools.get_product(session, product_id=product_id)
                if product_id
                else ToolResult("get_product", False, error_code="1001", summary="缺少商品 id")
            )
        elif name == "compare_products":
            raw_ids = args.get("product_ids") or []
            ids = [int(x) for x in raw_ids if str(x).isdigit()][:3]
            result = await tools.compare_products(session, product_ids=ids)
        elif name == "get_order":
            order_no = str(args.get("order_no") or "").strip()
            result = (
                await tools.get_order(
                    session,
                    order_no=order_no,
                    user=ctx.user,
                    phone_tail=_opt_str(args.get("phone_tail")),
                    trace_id=ctx.trace_id,
                )
                if order_no
                else ToolResult("get_order", False, error_code="1001", summary="缺少订单号")
            )
        elif name == "get_shipment":
            order_no = str(args.get("order_no") or "").strip()
            result = (
                await tools.get_shipment(
                    session,
                    order_no=order_no,
                    user=ctx.user,
                    phone_tail=_opt_str(args.get("phone_tail")),
                    trace_id=ctx.trace_id,
                )
                if order_no
                else ToolResult("get_shipment", False, error_code="1001", summary="缺少订单号")
            )
        elif name == "search_policy":
            result = await tools.search_policy(
                session, query=str(args.get("query") or ""), top_k=int(args.get("top_k") or 3)
            )
        else:
            result = ToolResult(name, False, error_code="1001", summary="未知工具")
    except Exception as exc:
        logger.warning("tool_failed", tool=name, error=repr(exc))
        result = ToolResult(name, False, error_code="5000", summary="查询失败，请如实说明")

    emit(
        {
            "type": "tool",
            "name": name,
            "status": "end",
            "summary": result.summary,
            "ok": result.ok,
            "latencyMs": result.latency_ms,
        }
    )
    return result


def _opt_str(value: object) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _opt_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return None


def _args_hint(name: str, args: dict[str, Any]) -> str:
    hints = {
        "search_products": "正在筛选商品…",
        "get_product": "正在取商品详情…",
        "compare_products": "正在对齐参数…",
        "get_order": "正在查询订单…",
        "get_shipment": "正在查询物流…",
        "search_policy": "正在查政策条文…",
    }
    return hints.get(name, f"正在调用 {name}…")


# ------------------------------------------------------------------ 销售
async def sales_node(state: GraphState) -> dict[str, object]:
    ctx = get_context()
    slots = dict(state.get("slots") or {})
    plan = [step for step in (state.get("tool_plan") or []) if step.get("tool") in _PRODUCT_TOOLS]

    if not plan:
        # 模型没给计划时用槽位补一个，保证"问商品一定有结果或明确没结果"
        if slots.get("product_id"):
            plan = [{"tool": "get_product", "args": {"product_id": slots["product_id"]}}]
        else:
            plan = [
                {
                    "tool": "search_products",
                    "args": {
                        "keyword": slots.get("keyword"),
                        "category": slots.get("category"),
                        "price_min": slots.get("price_min"),
                        "price_max": slots.get("price_max"),
                        "limit": get_settings().candidate_keep,
                    },
                }
            ]
    wants_compare = len(plan) > 1 and plan[1].get("tool") == "compare_products"
    if plan and plan[0].get("tool") == "search_products" and wants_compare:
        # 先搜再比：对比必须基于本轮结果，不能让模型自己编 id
        plan = plan[:1]

    facts: list[dict[str, Any]] = []
    trace: list[dict[str, Any]] = []
    citations: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []

    for step in plan:
        result = await _run_tool(ctx.session, str(step["tool"]), step.get("args") or {})
        facts.append(result.as_fact())
        trace.append(_trace_of(result))
        citations.extend(result.meta.get("citations") or [])
        if result.ok and isinstance(result.data, dict):
            items = result.data.get("items")
            if isinstance(items, list):
                candidates = [
                    {
                        "id": item.get("id"),
                        "name": item.get("name"),
                        "priceCents": item.get("priceCents"),
                    }
                    for item in items[: get_settings().candidate_keep]
                ]
            elif result.data.get("id") is not None:
                candidates = [
                    {
                        "id": result.data.get("id"),
                        "name": result.data.get("name"),
                        "priceCents": result.data.get("priceCents"),
                    }
                ]

    if candidates:
        slots["last_products"] = candidates

    return {
        "facts": facts,
        "tool_trace": trace,
        "citations": citations,
        "slots": slots,
        "route": Route.SALES.value,
    }


# ------------------------------------------------------------------ 订单
async def order_node(state: GraphState) -> dict[str, object]:
    ctx = get_context()
    slots = dict(state.get("slots") or {})
    order_no = str(slots.get("order_no") or "")
    intent = str(state.get("intent") or "")
    facts: list[dict[str, Any]] = []
    trace: list[dict[str, Any]] = []
    citations: list[dict[str, Any]] = []

    if order_no:
        order_result = await _run_tool(
            ctx.session,
            "get_order",
            {"order_no": order_no, "phone_tail": slots.get("phone_tail")},
        )
        facts.append(order_result.as_fact())
        trace.append(_trace_of(order_result))
        if order_result.ok:
            # 被授权访问的订单号允许在回答里出现
            ctx.allowed_order_nos.add(order_no)
            # 承接给下一轮："我要退刚才那单"不必再报一次订单号
            slots["last_order_no"] = order_no

        if intent == "order_status" and order_result.ok:
            shipment_result = await _run_tool(
                ctx.session,
                "get_shipment",
                {"order_no": order_no, "phone_tail": slots.get("phone_tail")},
            )
            facts.append(shipment_result.as_fact())
            trace.append(_trace_of(shipment_result))
    elif ctx.user is not None:
        # 没给订单号但已登录：列出最近 3 笔，让模型反问"是哪一笔"
        recent, _, _ = await order_service.list_user_orders(
            ctx.session, user_id=ctx.user.id, limit=3
        )
        counts = await order_service.count_items_by_order(ctx.session, [o.id for o in recent])
        facts.append(
            {
                "tool": "list_recent_orders",
                "ok": True,
                "data": {
                    "orders": [
                        {
                            "orderNo": order.order_no,
                            "status": order.status,
                            "statusLabel": tools.ORDER_STATUS_LABELS.get(
                                order.status, order.status
                            ),
                            "totalCents": order.total_cents,
                            "itemCount": counts.get(order.id, 0),
                            "createdAt": order.created_at.isoformat() if order.created_at else None,
                        }
                        for order in recent
                    ]
                },
            }
        )
        ctx.allowed_order_nos.update(order.order_no for order in recent)
    else:
        facts.append(
            {
                "tool": "get_order",
                "ok": False,
                "error": "2001",
                "hint": "未登录且没有订单号，无法查询订单",
            }
        )

    if intent == "after_sales" or _looks_policy_question(state, slots):
        # 售后必然要查政策依据；另外"订单到哪了？顺便问下退货运费谁出"这类多意图问句
        # 也要带上政策片段，否则用户会收到"只答了一半"的回答
        policy = await _run_tool(ctx.session, "search_policy", {"query": _policy_query(state)})
        facts.append(policy.as_fact())
        trace.append(_trace_of(policy))
        citations.extend(policy.meta.get("citations") or [])

    return {
        "facts": facts,
        "tool_trace": trace,
        "citations": citations,
        "slots": slots,
        "route": Route.ORDER.value,
    }


# 政策类关键词：多意图问句里用来判断"要不要顺带查一次知识库"
_POLICY_HINTS = (
    "运费",
    "邮费",
    "包邮",
    "政策",
    "规则",
    "规定",
    "发票",
    "保修",
    "质保",
    "七天",
    "无理由",
    "退款多久",
    "怎么退",
    "能不能退",
    "退换",
)


def _looks_policy_question(state: GraphState, slots: dict[str, Any]) -> bool:
    text = str(state.get("user_text") or "")
    if any(hint in text for hint in _POLICY_HINTS):
        return True
    # 模型主动规划了 search_policy 也算（它可能识别出口语化政策问题）
    return any(step.get("tool") == "search_policy" for step in (state.get("tool_plan") or []))


def _policy_query(state: GraphState) -> str:
    """政策检索的 query 必须是"本轮"的。

    不能用 `slots.keyword`：它是跨轮持久的，上一轮问"降噪耳机"留下的关键词
    会让这一轮问"七天无理由"时去检耳机（实测过：0 命中，模型只能回答"查不到"）。
    优先用模型在 tool_plan 里给的 query（它已把口语压成检索词），否则用原话。
    """
    for step in state.get("tool_plan") or []:
        if step.get("tool") == "search_policy":
            args = step.get("args") or {}
            query = str(args.get("query") or "").strip()
            if query:
                return query
    return str(state.get("user_text") or "").strip()


# ------------------------------------------------------------------ 政策检索
async def retrieve_node(state: GraphState) -> dict[str, object]:
    ctx = get_context()
    result = await _run_tool(
        ctx.session, "search_policy", {"query": _policy_query(state), "top_k": 3}
    )
    return {
        "facts": [result.as_fact()],
        "tool_trace": [_trace_of(result)],
        "citations": result.meta.get("citations") or [],
        "route": Route.RETRIEVE.value,
    }


# ------------------------------------------------------------------ 转人工
HANDOFF_MESSAGE = (
    "已经帮你登记转人工，客服会在 5 分钟内接入这个会话。"
    "在等待期间你可以继续把问题说清楚，接入后同事能看到完整上下文。"
)


async def handoff_node(state: GraphState) -> dict[str, object]:
    """转人工：幂等建单（同一会话只留一张未完结单），并把状态同步到会话上。

    连续两次听不懂（`low_confidence_limit`）也会走到这里，所以幂等是必须的——
    否则一个用户反复说"转人工"会开出十几张单，客服侧直接爆掉。
    """
    ctx = get_context()
    session_uuid = _as_uuid(ctx.session_id)
    if session_uuid is None:
        return {"intent": "handoff", "route": Route.HANDOFF.value, "draft": HANDOFF_MESSAGE}

    try:
        ticket, created = await handoff_service.create_ticket(
            ctx.session,
            session_id=session_uuid,
            user_id=ctx.user.id if ctx.user else None,
            reason=str(state.get("user_text") or ""),
        )
        await session_service.set_handoff_status(
            ctx.session, session_id=session_uuid, status=ticket.status
        )
    except Exception as exc:
        logger.warning("handoff_failed", error=repr(exc))
        return {
            "intent": "handoff",
            "route": Route.HANDOFF.value,
            "draft": (
                "转人工登记的时候出了点问题，你可以稍后再试一次，或者直接打客服电话 400-000-0000。"
            ),
        }

    status_label = handoff_service.STATUS_LABELS.get(ticket.status, ticket.status)
    if created:
        draft = (
            f"已经帮你登记转人工，工单号 {ticket.ticket_no}（{status_label}），"
            "客服会在 5 分钟内接入这个会话。"
            "等待期间你可以继续把问题说清楚，接入后同事能看到完整上下文。"
        )
    else:
        draft = (
            f"你已经在人工队列里了，工单号 {ticket.ticket_no}（{status_label}），"
            "客服接入后会直接看到这段对话，不用重复描述。"
        )
    emit(
        {
            "type": "action",
            "action": {
                "kind": "handoff_ticket",
                "ticketNo": ticket.ticket_no,
                "status": ticket.status,
                "statusLabel": status_label,
                "created": created,
            },
        }
    )
    return {"intent": "handoff", "route": Route.HANDOFF.value, "draft": draft}


# ------------------------------------------------------------------ 追问 / 静态回答
async def clarify_node(state: GraphState) -> dict[str, object]:
    question = state.get("clarify_question") or "能把问题说得再具体一点吗？"
    return {"draft": question, "route": Route.CLARIFY.value}


def _trace_of(result: ToolResult) -> dict[str, Any]:
    return {
        "name": result.name,
        "ok": result.ok,
        "summary": result.summary,
        "errorCode": result.error_code,
        "latencyMs": result.latency_ms,
    }


def _as_uuid(value: str) -> Any:
    from uuid import UUID

    try:
        return UUID(value)
    except (TypeError, ValueError):
        return None

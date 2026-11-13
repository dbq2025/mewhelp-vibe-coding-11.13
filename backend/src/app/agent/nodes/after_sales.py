"""节点：售后受理（确定性链路 + 二次确认 + 建单）。

为什么这个节点**不调模型**：
生成回答的成本是 0.8~1.2s，而"要不要退"这件事的判断依据必须是代码算出来的。
让模型写"已为你提交工单"，它就有概率在**没建单**的时候也这么写。所以终态文案固定模板：

    待确认 → 列出订单摘要与申请类型，等用户说"确认"
    确认   → 建单，返回工单号
    取消   → 什么都不做
    不可受理 → 说明原因（超期、未发货、已关闭…）

模板里能塞的只有来自 DB 的事实：订单号、状态、商品名、金额、工单号。
"""

from __future__ import annotations

from typing import Any

from app.agent import slots as slot_utils
from app.agent import tools
from app.agent.nodes.actions import _run_tool, _trace_of
from app.agent.runtime import emit, get_context
from app.agent.state import GraphState, Route
from app.core.logging import get_logger
from app.domain.services import after_sales as service
from app.domain.services import orders as order_service
from app.infra.db.models.order import Order

logger = get_logger(__name__)

MISSING_ORDER_MESSAGE = (
    "我需要先确认是哪一笔订单。把订单号发我（形如 20261101001），"
    "或者先让我看看你最近的订单，我再帮你选。"
)
MISSING_TYPE_MESSAGE = "你是想退货退款、换货，还是申请维修？说一种，我按对应流程帮你办。"
NOT_FOUND_MESSAGE = "我没查到这笔订单，或者它不属于当前账号。核对一下订单号，或者我帮你转人工核实。"


def _money(cents: int) -> str:
    return f"¥{cents / 100:.2f}"


def _order_summary(order: Order, rows: list[str]) -> str:
    items = "、".join(f"{item.name_snapshot}×{item.qty}" for item in order.items) or "（无明细）"
    status = tools.ORDER_STATUS_LABELS.get(order.status, order.status)
    return "\n".join(
        [
            f"· 订单号：{order.order_no}（{status}）",
            f"· 商品：{items}",
            f"· 金额：{_money(order.total_cents)}",
            *rows,
        ]
    )


async def after_sales_node(state: GraphState) -> dict[str, object]:
    ctx = get_context()
    slots = dict(state.get("slots") or {})
    order_no = str(slots.get("order_no") or slots.get("last_order_no") or "").strip()
    facts: list[dict[str, Any]] = []
    trace: list[dict[str, Any]] = []

    if not order_no:
        return _final(route=Route.AFTER_SALES.value, draft=MISSING_ORDER_MESSAGE, slots=slots)

    # 1) 鉴权取单：复用 get_order 工具（内部走 authz，越权与不存在同码，并落审计）
    order_result = await _run_tool(
        ctx.session,
        "get_order",
        {"order_no": order_no, "phone_tail": slots.get("phone_tail")},
    )
    facts.append(order_result.as_fact())
    trace.append(_trace_of(order_result))
    if not order_result.ok:
        return _final(
            route=Route.AFTER_SALES.value,
            draft=NOT_FOUND_MESSAGE,
            slots=slots,
            facts=facts,
            trace=trace,
        )
    ctx.allowed_order_nos.add(order_no)

    order = await order_service.get_order_detail(ctx.session, order_no)
    if order is None:  # 并发删除等极端情况：当作查不到，不抛 500
        return _final(
            route=Route.AFTER_SALES.value,
            draft=NOT_FOUND_MESSAGE,
            slots=slots,
            facts=facts,
            trace=trace,
        )
    slots["last_order_no"] = order.order_no

    # 已建单后说"算了"：单子不会因为一句话消失，只能如实告知撤销路径
    if state.get("action") == "revoke":
        last = slots.get("last_after_sales") or {}
        ticket_no = str(last.get("ticketNo") or "")
        return _final(
            route=Route.AFTER_SALES.value,
            draft=(
                f"这张单已经提交了（单号 {ticket_no}，待受理），没法直接撤回。"
                "如果需要撤销，我帮你登记转人工处理；也可以说说撤销原因，我记在工单上。"
            ),
            slots=slots,
            facts=facts,
            trace=trace,
        )

    # 2) 售后类型：本轮抽槽 > 待确认动作里记的 > 追问
    pending = slots.get(slot_utils.PENDING_ACTION)
    pending_kind = pending.get("type") if isinstance(pending, dict) else None
    kind = service.normalize_type(slots.get("after_sales_type")) or service.normalize_type(
        pending_kind
    )
    if not kind:
        return _final(
            route=Route.AFTER_SALES.value,
            draft=MISSING_TYPE_MESSAGE,
            slots=slots,
            facts=facts,
            trace=trace,
        )
    slots["after_sales_type"] = kind
    label = service.TYPE_LABELS[kind]

    # 用户主动取消：什么都不做，只回一句准确的
    if state.get("action") == "cancel":
        slots.pop(slot_utils.PENDING_ACTION, None)
        return _final(
            route=Route.AFTER_SALES.value,
            draft=f"好的，这次的「{label}」申请我不提交了。之后想办随时跟我说，订单信息我记着。",
            slots=slots,
            facts=facts,
            trace=trace,
        )

    # 3) 可受理判定（代码算，不让模型判）
    reason = str((pending or {}).get("reason") or "") if isinstance(pending, dict) else ""
    reason = reason or str(slots.get("after_sales_reason") or "")
    verdict = service.check_eligibility(order, kind, reason)
    if not verdict.ok:
        slots.pop(slot_utils.PENDING_ACTION, None)
        open_ticket = await service.find_open_ticket(ctx.session, order_id=order.id, kind=kind)
        extra = ""
        if open_ticket:
            state_label = service.STATUS_LABELS.get(open_ticket.status, open_ticket.status)
            extra = f"\n\n你之前提交的单号是 {open_ticket.ticket_no}，状态：{state_label}。"
        emit(
            {
                "type": "action",
                "action": {
                    "kind": "after_sales_rejected",
                    "orderNo": order.order_no,
                    "type": kind,
                    "typeLabel": label,
                    "message": verdict.hint,
                },
            }
        )
        return _final(
            route=Route.AFTER_SALES.value,
            draft=f"这笔订单现在申请不了「{label}」：{verdict.hint}{extra}",
            slots=slots,
            facts=facts,
            trace=trace,
        )

    # 4) 已确认 → 建单（幂等：同订单同类型未完结只保留一张）
    if state.get("action") == "commit":
        emit(
            {
                "type": "tool",
                "name": "create_after_sales",
                "status": "start",
                "summary": "正在提交申请…",
            }
        )
        try:
            ticket, created = await service.create_ticket(
                ctx.session,
                order=order,
                user_id=ctx.user.id if ctx.user else order.user_id,
                kind=kind,
                reason=reason or f"用户申请{label}",
                source="agent",
            )
        except Exception as exc:  # 建单失败必须让用户知道，不能"看起来成功"
            logger.warning("after_sale_create_failed", error=repr(exc), order_no=order.order_no)
            emit(
                {
                    "type": "tool",
                    "name": "create_after_sales",
                    "status": "end",
                    "ok": False,
                    "summary": "建单失败",
                    "latencyMs": 0,
                }
            )
            return _final(
                route=Route.AFTER_SALES.value,
                draft=(
                    "提交的时候系统出了点问题，单子没建成。"
                    "可以过一会儿再让我提交一次，或者我帮你转人工登记。"
                ),
                slots=slots,
                facts=facts,
                trace=trace,
            )

        slots.pop(slot_utils.PENDING_ACTION, None)
        slots["last_after_sales"] = {
            "ticketNo": ticket.ticket_no,
            "type": kind,
            "orderNo": order.order_no,
        }
        emit(
            {
                "type": "tool",
                "name": "create_after_sales",
                "status": "end",
                "ok": True,
                "summary": f"已建单 {ticket.ticket_no}",
                "latencyMs": 0,
            }
        )
        emit(
            {
                "type": "action",
                "action": {
                    "kind": "after_sales_done",
                    "ticketNo": ticket.ticket_no,
                    "orderNo": order.order_no,
                    "type": kind,
                    "typeLabel": label,
                    "status": ticket.status,
                    "statusLabel": service.STATUS_LABELS.get(ticket.status, ticket.status),
                    "created": created,
                },
            }
        )
        if created:
            draft = (
                f"已经帮你提交「{label}」申请，工单号 {ticket.ticket_no}。\n\n"
                f"当前状态：待受理。审核通过后按原支付方式退回，到账一般 3~5 个工作日。\n"
                f"想查进度随时问我这个单号就行。"
            )
        else:
            draft = (
                f"这笔订单已经有一张「{label}」单在处理中，单号 {ticket.ticket_no}，"
                f"状态：{service.STATUS_LABELS.get(ticket.status, ticket.status)}。\n\n"
                "不用重复提交，我按这张单跟进就行。"
            )
        return _final(
            route=Route.AFTER_SALES.value, draft=draft, slots=slots, facts=facts, trace=trace
        )

    # 5) 首次提出 → 生成待确认动作，把"要提交什么"明确摆给用户看
    rows = [f"· 申请事项：{label}"]
    if reason:
        rows.append(f"· 申请原因：{reason}")
    slots[slot_utils.PENDING_ACTION] = {
        "kind": "after_sales",
        "type": kind,
        "orderNo": order.order_no,
        "orderId": order.id,
        "reason": reason,
    }
    emit(
        {
            "type": "action",
            "action": {
                "kind": "after_sales_confirm",
                "orderNo": order.order_no,
                "type": kind,
                "typeLabel": label,
                "reason": reason,
                "confirmText": "确认提交",
                "cancelText": "先不申请",
                "summary": _order_summary(order, rows),
            },
        }
    )
    draft = (
        f"我核对到这笔订单：\n\n{_order_summary(order, rows)}\n\n"
        "确认无误的话回复「确认提交」，我这就帮你建单；"
        "如果哪里不对，告诉我要改哪一项。"
    )
    return _final(route=Route.AFTER_SALES.value, draft=draft, slots=slots, facts=facts, trace=trace)


def _final(
    *,
    route: str,
    draft: str,
    slots: dict[str, Any],
    facts: list[dict[str, Any]] | None = None,
    trace: list[dict[str, Any]] | None = None,
) -> dict[str, object]:
    return {
        "route": route,
        "draft": draft,
        "slots": slots,
        "facts": facts or [],
        "tool_trace": trace or [],
        "citations": [],
    }


# 供 order_flow 复用的订单号承接（"刚才那单"）
def remember_order(slots: dict[str, Any], order_no: str) -> dict[str, Any]:
    slots = dict(slots or {})
    slots["last_order_no"] = order_no
    return slots

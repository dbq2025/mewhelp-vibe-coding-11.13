"""售后受理：可受理判定 + 幂等建单 + 工单号生成。

为什么售后不走"让模型自由编排"（计划 4.2）：
建单是**写操作**，一次误建就是一张真实工单和一次退款流程。所以整条链路是确定性的：
    抽槽 → 鉴权（reuse authz）→ 可受理判定 → 二次确认 → 建单 → 幂等返回

三条硬规则：
1. **可受理判定在代码里**，不由模型判断"这笔能不能退"。模型只负责措辞。
2. **二次确认必过**：`pending_action` 落 `session_states.slots`，下一轮靠规则识别"确认"，
   不靠模型猜用户是不是同意了。
3. **幂等**：同一订单同一类型未完结的单只能有一张（应用层先查 + 部分唯一索引兜底）。
   用户连点两次"确认"不能变出两张退货单。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.infra.db.models.order import AfterSale, Order

logger = get_logger(__name__)

# 售后类型：只支持这三类。`refund`（仅退款）也走 return 通道，避免类型爆炸
TYPE_LABELS = {
    "return": "退货退款",
    "exchange": "换货",
    "repair": "维修",
}
TYPES = tuple(TYPE_LABELS)

# 状态机：pending → processing → done；任意未完结态可 rejected/closed
STATUS_LABELS = {
    "pending": "待受理",
    "processing": "处理中",
    "done": "已完成",
    "rejected": "已驳回",
    "closed": "已关闭",
}
OPEN_STATUSES = ("pending", "processing")
CLOSED_STATUSES = ("done", "rejected", "closed")

# 可受理的订单状态。pending_pay / closed 不能售后，pending_ship 建议直接取消订单
SHIPPED_STATUSES = ("shipped", "delivered")

# 7 天无理由的窗口（自签收起算）
NO_REASON_DAYS = 7
# 质量问题的关键词：出现这些词时不受 7 天限制
QUALITY_WORDS = (
    "坏",
    "破损",
    "摔",
    "裂",
    "碎",
    "漏",
    "不亮",
    "没反应",
    "故障",
    "质量",
    "瑕疵",
    "错发",
    "少发",
    "漏发",
    "假",
    "过期",
    "异味",
    "无法开机",
    "开不了机",
    "杂音",
    "噪音",
    "不响",
    "没声音",
    "无声",
    "不充电",
    "充不进",
    "充不上",
    "电池",
    "发热",
    "发烫",
    "断连",
    "卡顿",
    "黑屏",
    "死机",
    "划痕",
    "变形",
    "缺件",
    "漏电",
    "与描述不符",
    "货不对板",
)


@dataclass(frozen=True, slots=True)
class Eligibility:
    """可受理判定结果。`hint` 是给用户看的一句话，不是给模型的推理素材。"""

    ok: bool
    hint: str = ""
    # 需要用户改用别的路径（如"未发货请直接取消订单"）
    redirect: str | None = None


def normalize_type(raw: object) -> str | None:
    """把模型/前端给的类型收敛到三种。`refund` 归入 `return`（业务上同一通道）。"""
    value = str(raw or "").strip().lower()
    mapping = {
        "return": "return",
        "refund": "return",
        "退货": "return",
        "退款": "return",
        "exchange": "exchange",
        "换货": "exchange",
        "换一个": "exchange",
        "repair": "repair",
        "维修": "repair",
        "保修": "repair",
        "修": "repair",
    }
    return mapping.get(value)


def is_quality_issue(reason: str) -> bool:
    text_reason = reason or ""
    return any(word in text_reason for word in QUALITY_WORDS)


def check_eligibility(order: Order, kind: str, reason: str = "") -> Eligibility:
    """判定这笔订单能不能受理该类售后。纯函数，可单测，不查库。"""
    label = TYPE_LABELS.get(kind, "售后")

    if order.status in ("pending_pay",):
        return Eligibility(
            False, hint="这笔订单还没付款，不需要申请售后。付款后如果不想买了可以取消订单。"
        )
    if order.status == "closed":
        return Eligibility(
            False, hint="这笔订单已经关闭，无法再申请售后。如果确实有问题，我帮你转人工核实。"
        )
    if order.status == "refunding":
        return Eligibility(
            False,
            hint="这笔订单已经在退款流程里了，不用重复申请。我可以帮你查一下处理进度。",
        )
    if order.status == "pending_ship":
        return Eligibility(
            False,
            hint="这笔订单还没发货，直接取消订单更快，不用走售后流程。需要我帮你转人工取消吗？",
            redirect="cancel_order",
        )
    if order.status not in SHIPPED_STATUSES:
        return Eligibility(False, hint=f"当前订单状态不支持申请{label}。")

    if kind not in TYPES:
        return Eligibility(False, hint="售后类型只能是退货退款、换货或维修其中一种。")

    # 7 天无理由：只约束"非质量问题"的退货/换货
    if kind in ("return", "exchange") and not is_quality_issue(reason):
        start = order.paid_at or order.created_at
        if start is not None and datetime.now(UTC) - _aware(start) > timedelta(days=NO_REASON_DAYS):
            return Eligibility(
                False,
                hint=(
                    f"这笔订单已经超过签收后 {NO_REASON_DAYS} 天的无理由{label}期限。"
                    "如果是商品本身有质量问题，说下具体现象，我按质量问题帮你申请。"
                ),
            )
    return Eligibility(True)


def _aware(value: datetime) -> datetime:
    """DB 里是 timestamptz，取出来可能是 aware；本地 naive 值按 UTC 兜底。"""
    return value if value.tzinfo else value.replace(tzinfo=UTC)


async def find_open_ticket(session: AsyncSession, *, order_id: int, kind: str) -> AfterSale | None:
    ticket: AfterSale | None = await session.scalar(
        select(AfterSale).where(
            AfterSale.order_id == order_id,
            AfterSale.type == kind,
            AfterSale.status.in_(OPEN_STATUSES),
        )
    )
    return ticket


async def next_ticket_no(session: AsyncSession) -> str:
    """`AS` + 日期 + 4 位序号。序号来自数据库序列，并发下不会撞号。"""
    seq = await session.scalar(text("select nextval('after_sales_ticket_seq')"))
    stamp = datetime.now(UTC).strftime("%Y%m%d")
    return f"AS{stamp}{int(seq or 1) % 10000:04d}"


async def create_ticket(
    session: AsyncSession,
    *,
    order: Order,
    user_id: int,
    kind: str,
    reason: str = "",
    source: str = "agent",
) -> tuple[AfterSale, bool]:
    """建单。返回 (工单, 是否新建)：`created=False` 表示命中了已有未完结工单。

    幂等策略是"先查后插 + 唯一索引兜底"：正常路径命中已有单直接返回，
    并发路径下唯一索引报错、回滚后重查一次（此刻另一条事务已提交）。
    """
    existing = await find_open_ticket(session, order_id=order.id, kind=kind)
    if existing is not None:
        return existing, False

    ticket = AfterSale(
        ticket_no=await next_ticket_no(session),
        order_id=order.id,
        order_no=order.order_no,
        user_id=user_id,
        type=kind,
        status="pending",
        reason=(reason or "")[:500],
        source=source,
    )
    session.add(ticket)
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        again = await find_open_ticket(session, order_id=order.id, kind=kind)
        if again is not None:
            return again, False
        raise
    await session.refresh(ticket)
    logger.info(
        "after_sale_created",
        ticket_no=ticket.ticket_no,
        order_no=order.order_no,
        kind=kind,
        source=source,
    )
    return ticket, True


async def list_user_tickets(
    session: AsyncSession, *, user_id: int, limit: int = 10
) -> list[AfterSale]:
    rows = await session.scalars(
        select(AfterSale)
        .where(AfterSale.user_id == user_id)
        .order_by(AfterSale.id.desc())
        .limit(max(1, min(limit, 50)))
    )
    return list(rows)


async def count_open(session: AsyncSession, *, user_id: int) -> int:
    return int(
        await session.scalar(
            select(func.count())
            .select_from(AfterSale)
            .where(AfterSale.user_id == user_id, AfterSale.status.in_(OPEN_STATUSES))
        )
        or 0
    )

"""订单只读服务。

所有查询都带 user_id / 唯一业务号条件，不做"先全表捞出再过滤"（agent.md §12）。
"""

from __future__ import annotations

import base64
import binascii

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import InvalidParamError
from app.infra.db.models.order import Order, OrderItem, Shipment


def _encode_cursor(order_id: int) -> str:
    return base64.urlsafe_b64encode(str(order_id).encode()).decode()


def _decode_cursor(cursor: str) -> int:
    try:
        return int(base64.urlsafe_b64decode(cursor.encode()).decode())
    except (binascii.Error, UnicodeDecodeError, ValueError) as exc:
        raise InvalidParamError("cursor 不合法") from exc


async def list_user_orders(
    session: AsyncSession,
    *,
    user_id: int,
    status: str | None = None,
    limit: int = 20,
    cursor: str | None = None,
) -> tuple[list[Order], str | None, bool]:
    """按 id 倒序翻页（id 单调递增，等价于按创建时间倒序，且索引更省）。"""
    limit = max(1, min(limit, 100))
    stmt = select(Order).where(Order.user_id == user_id).order_by(Order.id.desc()).limit(limit + 1)
    if status:
        stmt = stmt.where(Order.status == status)
    if cursor:
        stmt = stmt.where(Order.id < _decode_cursor(cursor))

    orders = list((await session.scalars(stmt)).all())
    has_more = len(orders) > limit
    orders = orders[:limit]
    next_cursor = _encode_cursor(orders[-1].id) if has_more and orders else None
    return orders, next_cursor, has_more


async def get_order_by_no(session: AsyncSession, order_no: str) -> Order | None:
    order: Order | None = await session.scalar(select(Order).where(Order.order_no == order_no))
    return order


async def get_order_detail(session: AsyncSession, order_no: str) -> Order | None:
    """带明细与物流的一次性加载，避免路由里 N+1。"""
    order: Order | None = await session.scalar(
        select(Order)
        .where(Order.order_no == order_no)
        .options(selectinload(Order.items), selectinload(Order.shipment))
    )
    return order


async def get_shipment(session: AsyncSession, order_id: int) -> Shipment | None:
    shipment: Shipment | None = await session.scalar(
        select(Shipment).where(Shipment.order_id == order_id)
    )
    return shipment


async def count_items_by_order(session: AsyncSession, order_ids: list[int]) -> dict[int, int]:
    """列表页只需要"共 N 件"，一次 group by 拿全，不做逐单 count。"""
    if not order_ids:
        return {}
    rows = await session.execute(
        select(OrderItem.order_id, OrderItem.qty).where(OrderItem.order_id.in_(order_ids))
    )
    counts: dict[int, int] = {}
    for order_id, qty in rows.all():
        counts[order_id] = counts.get(order_id, 0) + int(qty)
    return counts

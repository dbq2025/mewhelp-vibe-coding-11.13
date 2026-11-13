"""Agent 工具层：把 domain service 包装成"不会抛异常给模型"的统一契约。

契约（计划 4.3）：`{ok, data | error_code, summary, latency_ms}`。
**工具异常绝不抛给 LLM**——否则模型会看到一段 traceback，然后开始编造"查询失败但价格为…"。
失败时只给它一句人话，并要求它如实说明查不到。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.logging import get_logger
from app.domain.policies.authz import assert_order_access
from app.domain.services import catalog as catalog_service
from app.domain.services import orders as order_service
from app.infra.db.models.order import Order
from app.infra.db.models.user import User
from app.rag import retriever

logger = get_logger(__name__)

ORDER_STATUS_LABELS = {
    "pending_pay": "待付款",
    "pending_ship": "待发货",
    "shipped": "已发货",
    "delivered": "已签收",
    "refunding": "退款中",
    "closed": "已关闭",
}


@dataclass
class ToolResult:
    name: str
    ok: bool
    data: Any = None
    summary: str = ""
    error_code: str | None = None
    latency_ms: int = 0
    meta: dict[str, Any] = field(default_factory=dict)

    def as_fact(self) -> dict[str, Any]:
        """交给 compose 的事实块。失败也要给模型一句明确结论。"""
        if self.ok:
            return {"tool": self.name, "ok": True, "data": self.data}
        return {
            "tool": self.name,
            "ok": False,
            "error": self.error_code,
            "hint": self.summary or "该查询失败，不要猜测结果",
        }


def _elapsed(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


async def search_products(
    session: AsyncSession,
    *,
    keyword: str | None = None,
    category: str | None = None,
    price_min: int | None = None,
    price_max: int | None = None,
    sort: str = "recommend",
    limit: int = 5,
) -> ToolResult:
    """商品检索。价格入参单位是**分**，模型给元时由 understand 层换算，工具不再猜。"""
    start = time.perf_counter()
    limit = max(1, min(int(limit or 5), 10))
    sort_key = sort if sort in {"recommend", "price_asc", "price_desc", "newest"} else "recommend"
    rows, _, _ = await catalog_service.list_products(
        session,
        q=keyword,
        category=category,
        price_min=price_min,
        price_max=price_max,
        sort=sort_key,  # type: ignore[arg-type]
        limit=limit,
    )
    items = [
        {
            "id": product.id,
            "name": product.name,
            "brand": product.brand,
            "priceCents": product.price_cents,
            "stock": product.stock,
            "category": category_name,
        }
        for product, category_name in rows
    ]
    summary = f"找到 {len(items)} 件商品" if items else "没有符合条件的商品"
    return ToolResult(
        name="search_products",
        ok=True,
        data={"items": items, "filters": {"keyword": keyword, "priceMax": price_max}},
        summary=summary,
        latency_ms=_elapsed(start),
    )


async def get_product(session: AsyncSession, *, product_id: int) -> ToolResult:
    start = time.perf_counter()
    row = await catalog_service.get_product(session, int(product_id))
    if row is None:
        return ToolResult(
            name="get_product",
            ok=False,
            error_code="2004",
            summary="商品不存在",
            latency_ms=_elapsed(start),
        )
    product, category_name = row
    return ToolResult(
        name="get_product",
        ok=True,
        data={
            "id": product.id,
            "name": product.name,
            "brand": product.brand,
            "priceCents": product.price_cents,
            "stock": product.stock,
            "status": product.status,
            "category": category_name,
            "attrs": product.attrs,
            "description": product.description,
        },
        summary=f"已取到 {product.name} 的详情",
        latency_ms=_elapsed(start),
    )


async def compare_products(session: AsyncSession, *, product_ids: list[int]) -> ToolResult:
    """属性对齐表。只允许 2~3 个，超过就退化——不做 10 个商品的表格。"""
    start = time.perf_counter()
    ids = [int(pid) for pid in (product_ids or [])][:3]
    if len(ids) < 2:
        return ToolResult(
            name="compare_products",
            ok=False,
            error_code="1001",
            summary="对比至少需要两个商品",
            latency_ms=_elapsed(start),
        )
    products = []
    for pid in ids:
        row = await catalog_service.get_product(session, pid)
        if row is None:
            continue
        product, category_name = row
        products.append(
            {
                "id": product.id,
                "name": product.name,
                "brand": product.brand,
                "priceCents": product.price_cents,
                "category": category_name,
                "attrs": product.attrs,
            }
        )
    if len(products) < 2:
        return ToolResult(
            name="compare_products",
            ok=False,
            error_code="2004",
            summary="参与对比的商品不存在",
            latency_ms=_elapsed(start),
        )
    return ToolResult(
        name="compare_products",
        ok=True,
        data={"products": products},
        summary=f"已对齐 {len(products)} 个商品的属性",
        latency_ms=_elapsed(start),
    )


async def get_order(
    session: AsyncSession,
    *,
    order_no: str,
    user: User | None,
    phone_tail: str | None,
    trace_id: str,
) -> ToolResult:
    start = time.perf_counter()
    order = await order_service.get_order_detail(session, order_no)
    try:
        checked = await assert_order_access(
            session,
            order,
            order_no=order_no,
            user=user,
            phone_tail=phone_tail,
            actor=f"user:{user.id}" if user else "guest",
            trace_id=trace_id,
        )
    except AppError:
        # 不把"存在但无权"和"不存在"区分开，模型也无从泄漏
        return ToolResult(
            name="get_order",
            ok=False,
            error_code="2003",
            summary="没有查到这笔订单，或者它不属于当前账号",
            latency_ms=_elapsed(start),
        )

    payload = _order_payload(checked)
    return ToolResult(
        name="get_order",
        ok=True,
        data=payload,
        summary=f"订单 {_mask(order_no)} 状态：{payload['statusLabel']}",
        latency_ms=_elapsed(start),
    )


async def get_shipment(
    session: AsyncSession,
    *,
    order_no: str,
    user: User | None,
    phone_tail: str | None,
    trace_id: str,
) -> ToolResult:
    start = time.perf_counter()
    order = await order_service.get_order_detail(session, order_no)
    try:
        checked = await assert_order_access(
            session,
            order,
            order_no=order_no,
            user=user,
            phone_tail=phone_tail,
            actor=f"user:{user.id}" if user else "guest",
            trace_id=trace_id,
        )
    except AppError:
        return ToolResult(
            name="get_shipment",
            ok=False,
            error_code="2003",
            summary="没有查到这笔订单，或者它不属于当前账号",
            latency_ms=_elapsed(start),
        )

    shipment = await order_service.get_shipment(session, checked.id)
    if shipment is None:
        return ToolResult(
            name="get_shipment",
            ok=True,
            data={"orderNo": checked.order_no, "shipped": False},
            summary="该订单尚未发货，没有物流记录",
            latency_ms=_elapsed(start),
        )
    events = [
        {
            "time": str(event.get("time", "")),
            "status": str(event.get("status", "")),
            "desc": str(event.get("desc", "")),
        }
        for event in (shipment.events or [])
    ]
    return ToolResult(
        name="get_shipment",
        ok=True,
        data={
            "orderNo": checked.order_no,
            "shipped": True,
            "carrier": shipment.carrier,
            "trackingNo": shipment.tracking_no,
            "status": shipment.status,
            "latest": events[-1] if events else None,
            "events": events[-5:],
        },
        summary=f"{shipment.carrier} 已更新 {len(events)} 个节点",
        latency_ms=_elapsed(start),
    )


async def search_policy(session: AsyncSession, *, query: str, top_k: int = 3) -> ToolResult:
    start = time.perf_counter()
    chunks = await retriever.search(session, query, top_k=max(1, min(int(top_k or 3), 5)))
    citations = [chunk.to_citation(index + 1) for index, chunk in enumerate(chunks)]
    return ToolResult(
        name="search_policy",
        ok=True,
        data={
            "chunks": [
                {
                    "index": chunk.to_citation(index + 1)["index"],
                    "title": chunk.doc_title,
                    "content": chunk.content,
                    "distance": round(chunk.distance, 4),
                }
                for index, chunk in enumerate(chunks)
            ]
        },
        summary=f"命中 {len(chunks)} 条政策片段" if chunks else "知识库里没有匹配的政策",
        latency_ms=_elapsed(start),
        meta={"citations": citations},
    )


def _order_payload(order: Order) -> dict[str, Any]:
    return {
        "orderNo": order.order_no,
        "status": order.status,
        "statusLabel": ORDER_STATUS_LABELS.get(order.status, order.status),
        "totalCents": order.total_cents,
        "itemCount": sum(item.qty for item in order.items),
        "items": [
            {"name": item.name_snapshot, "qty": item.qty, "unitPriceCents": item.unit_price_cents}
            for item in order.items
        ],
        "createdAt": order.created_at.isoformat() if order.created_at else None,
        "paidAt": order.paid_at.isoformat() if order.paid_at else None,
        "receiverPhoneTail": order.receiver_phone_tail,
        "receiverAddressMasked": order.receiver_address_masked,
    }


def _mask(order_no: str) -> str:
    return f"{order_no[:4]}***{order_no[-3:]}" if len(order_no) > 7 else order_no

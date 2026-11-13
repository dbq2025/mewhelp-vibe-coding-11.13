"""订单与物流路由（api.md §2.6）。

鉴权口径：
- `GET /orders` 必须登录，只返回本人的单；
- `GET /orders/{orderNo}` 登录用户免尾号（且只能看自己的），游客需 `phoneTail`；
- 越权 / 不存在 / 尾号错 → 统一 2003，并落 `audit_events`。
"""

from typing import Annotated

from fastapi import APIRouter, Query, Request

from app.api.deps import CurrentUser, OptionalUser
from app.api.schemas.common import ApiResponse, PageData, PageMeta, ok
from app.api.schemas.order import (
    OrderBrief,
    OrderDetail,
    OrderItemOut,
    ShipmentEvent,
    ShipmentOut,
)
from app.core.deps import DbSession
from app.core.trace import get_trace_id
from app.domain.policies.authz import assert_order_access
from app.domain.services import orders as order_service
from app.infra.db.models.order import Shipment

router = APIRouter(prefix="/orders", tags=["orders"])


def _shipment_out(shipment: Shipment | None) -> ShipmentOut | None:
    """Shipment ORM → DTO。events 是 JSONB，字段缺失按空串补齐，不让前端处理 null。"""
    if shipment is None:
        return None
    return ShipmentOut(
        carrier=shipment.carrier,
        trackingNo=shipment.tracking_no,
        status=shipment.status,
        events=[
            ShipmentEvent(
                time=str(event.get("time", "")),
                status=str(event.get("status", "")),
                desc=str(event.get("desc", "")),
            )
            for event in (shipment.events or [])
        ],
    )


@router.get("", response_model=ApiResponse[PageData[OrderBrief]], summary="我的订单")
async def list_my_orders(
    user: CurrentUser,
    session: DbSession,
    status: Annotated[str | None, Query(max_length=20)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query(max_length=128)] = None,
) -> ApiResponse[PageData[OrderBrief]]:
    rows, next_cursor, has_more = await order_service.list_user_orders(
        session, user_id=user.id, status=status, limit=limit, cursor=cursor
    )
    counts = await order_service.count_items_by_order(session, [o.id for o in rows])
    items = [
        OrderBrief(
            orderNo=order.order_no,
            status=order.status,
            totalCents=order.total_cents,
            itemCount=counts.get(order.id, 0),
            createdAt=order.created_at,
        )
        for order in rows
    ]
    return ok(
        PageData[OrderBrief](items=items, page=PageMeta(nextCursor=next_cursor, hasMore=has_more))
    )


@router.get("/{order_no}", response_model=ApiResponse[OrderDetail], summary="订单详情")
async def get_order(
    order_no: str,
    request: Request,
    session: DbSession,
    user: OptionalUser,
    phone_tail: Annotated[
        str | None,
        Query(alias="phoneTail", pattern=r"^\d{4}$", description="游客必填：收货手机尾号 4 位"),
    ] = None,
) -> ApiResponse[OrderDetail]:
    order = await order_service.get_order_detail(session, order_no)
    checked = await assert_order_access(
        session,
        order,
        order_no=order_no,
        user=user,
        phone_tail=phone_tail,
        actor=getattr(request.state, "actor", "guest"),
        trace_id=get_trace_id(),
    )

    shipment_out = _shipment_out(checked.shipment)

    return ok(
        OrderDetail(
            orderNo=checked.order_no,
            status=checked.status,
            totalCents=checked.total_cents,
            itemCount=sum(item.qty for item in checked.items),
            createdAt=checked.created_at,
            paidAt=checked.paid_at,
            receiverPhoneTail=checked.receiver_phone_tail,
            receiverAddressMasked=checked.receiver_address_masked,
            items=[
                OrderItemOut(
                    productId=item.product_id,
                    sku=item.sku_snapshot,
                    name=item.name_snapshot,
                    qty=item.qty,
                    unitPriceCents=item.unit_price_cents,
                )
                for item in checked.items
            ],
            shipment=shipment_out,
        )
    )


@router.get(
    "/{order_no}/shipment",
    response_model=ApiResponse[ShipmentOut | None],
    summary="物流轨迹",
)
async def get_shipment(
    order_no: str,
    request: Request,
    session: DbSession,
    user: OptionalUser,
    phone_tail: Annotated[str | None, Query(alias="phoneTail", pattern=r"^\d{4}$")] = None,
) -> ApiResponse[ShipmentOut | None]:
    order = await order_service.get_order_by_no(session, order_no)
    checked = await assert_order_access(
        session,
        order,
        order_no=order_no,
        user=user,
        phone_tail=phone_tail,
        actor=getattr(request.state, "actor", "guest"),
        trace_id=get_trace_id(),
    )
    shipment = await order_service.get_shipment(session, checked.id)
    if shipment is None:
        # 未发货不是错误：返回 null，让 Agent 说"还没发货"，而不是 404
        return ok(None)
    return ok(_shipment_out(shipment))

"""订单 / 物流接口响应体（api.md §2.6）。

注意：响应里**不含**完整手机号与详细地址，只有尾号与脱敏地址（计划 5.1）。
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class OrderItemOut(BaseModel):
    productId: int
    sku: str
    name: str
    qty: int
    unitPriceCents: int


class ShipmentEvent(BaseModel):
    time: str
    status: str
    desc: str


class ShipmentOut(BaseModel):
    carrier: str
    trackingNo: str
    status: str
    events: list[ShipmentEvent] = Field(default_factory=list)


class OrderBrief(BaseModel):
    orderNo: str
    status: str
    totalCents: int
    itemCount: int
    createdAt: datetime


class OrderDetail(OrderBrief):
    receiverPhoneTail: str
    receiverAddressMasked: str
    items: list[OrderItemOut] = Field(default_factory=list)
    shipment: ShipmentOut | None = None
    paidAt: datetime | None = None


class AuditMeta(BaseModel):
    """调试用元信息，仅本地环境返回（越权排查时看审计是否落库）。"""

    traceId: str = ""
    extra: dict[str, Any] = Field(default_factory=dict)

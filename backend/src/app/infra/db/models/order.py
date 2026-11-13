"""订单、订单明细、物流、售后。

隐私约束（计划 5.1）：只存脱敏后的收货信息；完整手机号/地址一律不落库。
明细存 sku/名称/单价快照，避免商品改名影响历史订单展示。
"""

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, ForeignKey, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.infra.db.base import Base


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (Index("idx_orders_user_created", "user_id", "created_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    order_no: Mapped[str] = mapped_column(String(32), unique=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(20))  # pending_pay/pending_ship/shipped/...
    total_cents: Mapped[int] = mapped_column(BigInteger)
    receiver_phone_tail: Mapped[str] = mapped_column(String(4))
    receiver_address_masked: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    paid_at: Mapped[datetime | None] = mapped_column(nullable=True)


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    order_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("orders.id", ondelete="CASCADE"), index=True
    )
    product_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("products.id"))
    sku_snapshot: Mapped[str] = mapped_column(String(40))
    name_snapshot: Mapped[str] = mapped_column(String(200))
    qty: Mapped[int] = mapped_column(default=1)
    unit_price_cents: Mapped[int] = mapped_column(BigInteger)


class Shipment(Base):
    __tablename__ = "shipments"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    order_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("orders.id", ondelete="CASCADE"), unique=True
    )
    carrier: Mapped[str] = mapped_column(String(30))
    tracking_no: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20))
    events: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class AfterSale(Base):
    __tablename__ = "after_sales"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ticket_no: Mapped[str] = mapped_column(String(32), unique=True)
    order_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("orders.id", ondelete="CASCADE"), index=True
    )
    order_no: Mapped[str] = mapped_column(String(32), index=True)  # 快照，便于按单号排查
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), index=True)
    type: Mapped[str] = mapped_column(String(16))  # return / exchange / repair
    status: Mapped[str] = mapped_column(String(20), default="pending")
    reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

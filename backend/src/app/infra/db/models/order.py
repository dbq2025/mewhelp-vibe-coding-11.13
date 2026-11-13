"""订单、订单明细、物流、售后。

隐私约束（计划 5.1）：只存脱敏后的收货信息；完整手机号/地址一律不落库。
明细存 sku/名称/单价快照，避免商品改名影响历史订单展示。
"""

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, ForeignKey, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

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

    # 明细与物流：只在详情/售后链路加载，列表页走 group by 统计（避免 N+1）
    items: Mapped[list["OrderItem"]] = relationship(
        back_populates="order", cascade="all, delete-orphan", lazy="raise"
    )
    shipment: Mapped["Shipment | None"] = relationship(
        back_populates="order", cascade="all, delete-orphan", uselist=False, lazy="raise"
    )


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

    order: Mapped["Order"] = relationship(back_populates="items", lazy="raise")


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

    order: Mapped["Order"] = relationship(back_populates="shipment", lazy="raise")


class AfterSale(Base):
    __tablename__ = "after_sales"
    __table_args__ = (
        # 幂等兜底：同一订单同一类型同时只能有一张未完结的单
        # （应用层先查后插，这里是并发下的最终裁判）
        Index(
            "uk_after_sales_open",
            "order_id",
            "type",
            unique=True,
            postgresql_where=text("status in ('pending','processing')"),
        ),
    )

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
    # 建单来源：agent（对话里二次确认后建） / api（前端直接提交）。
    # 排查"工单是谁开的"时要能一眼分开，P4 的转化率统计也依赖它。
    source: Mapped[str] = mapped_column(String(16), default="agent")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

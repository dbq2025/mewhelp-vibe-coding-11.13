"""p3 after sales and handoff

- `after_sales`：补 `source`（agent/api/seed）与 `updated_at`；加"同订单同类型未完结唯一"部分索引
- `handoff_tickets`：补 `ticket_no` / `user_id` / `updated_at`；加"同会话未完结唯一"部分索引
- 新增两个工单号序列（并发安全，避免 `max(id)+1` 竞态）

注意：NOT NULL 列必须"先加可空 → 回填 → 改非空"，直接 add_column(nullable=False)
在已有数据的表上会失败。`after_sales` 现有 3 行种子数据（source 记 `seed`）。

Revision ID: d1b67e9e6b32
Revises: 3567da1bb39f
Create Date: 2026-11-13 13:47:28.949854

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d1b67e9e6b32"
down_revision: str | Sequence[str] | None = "3567da1bb39f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # --- 工单号序列（先建序列，后续代码直接 nextval）---
    op.execute("create sequence if not exists after_sales_ticket_seq")
    op.execute("create sequence if not exists handoff_ticket_seq")
    # 已有售后数据要跳过已占用的号段，否则新单会撞号
    op.execute(
        "select setval('after_sales_ticket_seq', coalesce((select max(id) from after_sales), 1))"
    )

    # --- after_sales ---
    op.add_column(
        "after_sales",
        sa.Column("source", sa.String(length=16), nullable=True),
    )
    op.execute("update after_sales set source = 'seed' where source is null")
    op.alter_column("after_sales", "source", nullable=False, server_default="agent")
    op.add_column(
        "after_sales",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "uk_after_sales_open",
        "after_sales",
        ["order_id", "type"],
        unique=True,
        postgresql_where=sa.text("status in ('pending','processing')"),
    )

    # --- handoff_tickets ---
    op.add_column("handoff_tickets", sa.Column("ticket_no", sa.String(length=32), nullable=True))
    # 先给历史行一个占位号，避免 NOT NULL 失败（本地表为空，生产可能不为空）
    op.execute(
        "update handoff_tickets set ticket_no = 'HO_LEGACY_' || id::text where ticket_no is null"
    )
    op.alter_column("handoff_tickets", "ticket_no", nullable=False)
    op.create_unique_constraint(
        op.f("uq_handoff_tickets_ticket_no"), "handoff_tickets", ["ticket_no"]
    )
    op.add_column("handoff_tickets", sa.Column("user_id", sa.BigInteger(), nullable=True))
    op.create_index(
        op.f("ix_handoff_tickets_user_id"), "handoff_tickets", ["user_id"], unique=False
    )
    op.create_foreign_key(
        op.f("fk_handoff_tickets_user_id_users"),
        "handoff_tickets",
        "users",
        ["user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column(
        "handoff_tickets",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "uk_handoff_open_per_session",
        "handoff_tickets",
        ["session_id"],
        unique=True,
        postgresql_where=sa.text("status in ('pending','accepted')"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "uk_handoff_open_per_session",
        table_name="handoff_tickets",
        postgresql_where=sa.text("status in ('pending','accepted')"),
    )
    op.drop_column("handoff_tickets", "updated_at")
    op.drop_constraint(
        op.f("fk_handoff_tickets_user_id_users"), "handoff_tickets", type_="foreignkey"
    )
    op.drop_index(op.f("ix_handoff_tickets_user_id"), table_name="handoff_tickets")
    op.drop_column("handoff_tickets", "user_id")
    op.drop_constraint(op.f("uq_handoff_tickets_ticket_no"), "handoff_tickets", type_="unique")
    op.drop_column("handoff_tickets", "ticket_no")

    op.drop_index(
        "uk_after_sales_open",
        table_name="after_sales",
        postgresql_where=sa.text("status in ('pending','processing')"),
    )
    op.drop_column("after_sales", "updated_at")
    op.drop_column("after_sales", "source")

    op.execute("drop sequence if exists handoff_ticket_seq")
    op.execute("drop sequence if exists after_sales_ticket_seq")

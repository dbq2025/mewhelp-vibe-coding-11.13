"""数据库基类：命名约定 + 时间类型映射。

命名约定必须固定，否则 Alembic 自动生成的约束名在每次迁移里都不同，
回滚脚本会变得不可靠（agent.md §8）。
"""

from datetime import datetime
from typing import Any, ClassVar

from sqlalchemy import BigInteger, DateTime, MetaData
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    # 所有 Mapped[datetime] 默认落成 timestamptz，禁止存无时区时间（agent.md §8）
    type_annotation_map: ClassVar[dict[Any, Any]] = {
        datetime: DateTime(timezone=True),
        dict[str, Any]: JSONB,
        list[float]: JSONB,
    }

    def __repr__(self) -> str:
        pk = getattr(self, "id", None)
        return f"<{type(self).__name__} id={pk}>"


# 金额一律整数分（agent.md §6），统一用 BigInteger 保存，避免 32 位溢出
MoneyColumn = BigInteger

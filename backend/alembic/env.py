"""Alembic 环境（异步）。

连接串来自 app.core.config（与应用同源），避免两份配置漂移导致迁移打错库。
不调用 logging.config.fileConfig：日志统一由 app.core.logging 负责。
"""

import asyncio

from alembic import context
from sqlalchemy import Connection, pool
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.sql.schema import SchemaItem

from app.core.config import get_settings
from app.infra.db.models import Base

config = context.config
target_metadata = Base.metadata
DB_URL = get_settings().pg_dsn


def _include_object(
    obj: SchemaItem, name: str | None, type_: str, reflected: bool, compare_to: object
) -> bool:
    # 扩展自带对象不纳入版本管理，避免 autogenerate 反复生成删表
    excluded_prefixes = ("spatial_ref_sys", "pg_stat_")
    return not (type_ == "table" and name is not None and name.startswith(excluded_prefixes))


def run_migrations_offline() -> None:
    context.configure(
        url=DB_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
        include_object=_include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        include_object=_include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(DB_URL, poolclass=pool.NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(_do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())

"""异步引擎与 Session 工厂。infra 层，不得 import 上层模块（agent.md §2）。"""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings

_settings = get_settings()

engine: AsyncEngine = create_async_engine(
    _settings.pg_dsn,
    pool_size=_settings.db_pool_size,
    max_overflow=_settings.db_max_overflow,
    pool_pre_ping=True,
    echo=_settings.db_echo,
)

SessionFactory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    engine, expire_on_commit=False, autoflush=False
)


async def get_db_session() -> AsyncIterator[AsyncSession]:
    """FastAPI 依赖：每个请求一个 session，请求结束自动关闭。

    这里不 commit、不 rollback —— 事务边界由 service/repository 显式控制，
    避免"读接口顺手提交了别人的脏数据"。
    """
    async with SessionFactory() as session:
        yield session


async def dispose_engine() -> None:
    await engine.dispose()

"""FastAPI 依赖：跨路由复用的注入类型。"""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.db.session import get_db_session

DbSession = Annotated[AsyncSession, Depends(get_db_session)]

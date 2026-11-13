"""认证依赖：游客 / 登录用户两种身份。

规则（api.md §1.4）：
- 没有 Authorization 头 → 游客身份（`user=None`），由端点自己决定是否允许；
- 有头但无效/过期 → 直接 401，不静默降级为游客（否则越权测试会变成"静默放行"）。
"""

from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select

from app.core.deps import DbSession
from app.core.errors import UnauthenticatedError
from app.core.security import decode_access_token
from app.infra.db.models.user import User

_bearer = HTTPBearer(auto_error=False, description="JWT access token")


async def get_optional_user(
    request: Request,
    session: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)] = None,
) -> User | None:
    """解析可选身份；同时把 actor 字符串挂到 request.state 供审计使用。"""
    if credentials is None or not credentials.credentials:
        request.state.actor = "guest"
        return None

    user_id = decode_access_token(credentials.credentials)
    user = await session.scalar(select(User).where(User.id == user_id))
    if user is None:
        raise UnauthenticatedError("登录状态无效，请重新登录")
    request.state.actor = f"user:{user.id}"
    return user


async def get_current_user(
    user: Annotated[User | None, Depends(get_optional_user)],
) -> User:
    if user is None:
        raise UnauthenticatedError("请先登录")
    return user


OptionalUser = Annotated[User | None, Depends(get_optional_user)]
CurrentUser = Annotated[User, Depends(get_current_user)]

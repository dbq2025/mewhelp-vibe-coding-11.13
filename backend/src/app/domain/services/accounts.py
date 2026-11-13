"""账号服务：注册、登录、查询（domain 层，不含 HTTP 细节）。

为什么会话/订单服务都走 domain/services：路由只做参数收发，
业务规则（唯一性、鉴权、状态机）集中在 service 里，方便单测与后续 tool 复用。
"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import InvalidParamError, UnauthenticatedError
from app.core.security import create_access_token, hash_password, verify_password
from app.infra.db.models.user import User


async def register_user(
    session: AsyncSession, *, phone: str, password: str, nickname: str
) -> tuple[User, str, datetime]:
    """注册并直接签发 token。返回 (user, token, expires_at)。"""
    user = User(
        phone=phone,
        nickname=nickname or f"用户{phone[-4:]}",
        password_hash=hash_password(password),
    )
    session.add(user)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        # 并发下唯一索引是最终裁判，先查后插只能挡住大多数情况
        raise InvalidParamError("该手机号已注册") from exc

    await session.refresh(user)
    token, expires_at = create_access_token(user.id)
    return user, token, expires_at


async def login_user(
    session: AsyncSession, *, phone: str, password: str
) -> tuple[User, str, datetime]:
    user = await session.scalar(select(User).where(User.phone == phone))
    # 用户不存在与密码错误返回同一提示，避免手机号枚举
    if user is None or not verify_password(password, user.password_hash):
        raise UnauthenticatedError("手机号或密码错误")
    token, expires_at = create_access_token(user.id)
    return user, token, expires_at

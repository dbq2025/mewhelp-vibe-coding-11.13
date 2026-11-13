"""账号路由（api.md §2.2）：注册 / 登录 / 当前用户。"""

from fastapi import APIRouter, status

from app.api.deps import CurrentUser
from app.api.schemas.auth import LoginIn, RegisterIn, TokenOut, UserOut
from app.api.schemas.common import ApiResponse, ok
from app.core.deps import DbSession
from app.core.security import mask_phone
from app.domain.services import accounts
from app.infra.db.models.user import User

router = APIRouter(prefix="/auth", tags=["auth"])


def _user_out(user: User) -> UserOut:
    """对外视图：手机号一律脱敏（api.md §2.2），不返回密码散列。"""
    return UserOut(id=user.id, phone=mask_phone(user.phone), nickname=user.nickname)


@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    response_model=ApiResponse[TokenOut],
    summary="注册并登录",
)
async def register(payload: RegisterIn, session: DbSession) -> ApiResponse[TokenOut]:
    user, token, expires_at = await accounts.register_user(
        session, phone=payload.phone, password=payload.password, nickname=payload.nickname
    )
    return ok(
        TokenOut(
            token=token,
            expiresAt=expires_at,
            user=_user_out(user),
        )
    )


@router.post("/login", response_model=ApiResponse[TokenOut], summary="登录")
async def login(payload: LoginIn, session: DbSession) -> ApiResponse[TokenOut]:
    user, token, expires_at = await accounts.login_user(
        session, phone=payload.phone, password=payload.password
    )
    return ok(
        TokenOut(
            token=token,
            expiresAt=expires_at,
            user=_user_out(user),
        )
    )


@router.get("/me", response_model=ApiResponse[UserOut], summary="当前用户")
async def me(user: CurrentUser) -> ApiResponse[UserOut]:
    return ok(_user_out(user))

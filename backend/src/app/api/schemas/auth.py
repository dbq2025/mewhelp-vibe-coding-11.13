"""账号相关请求/响应体（api.md §2.2）。"""

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

_PHONE_PATTERN = r"^1[3-9]\d{9}$"


class RegisterIn(BaseModel):
    phone: str = Field(pattern=_PHONE_PATTERN, description="11 位手机号")
    password: str = Field(min_length=8, max_length=64, description="至少 8 位")
    nickname: str = Field(default="", max_length=50)

    @field_validator("password")
    @classmethod
    def _strength(cls, value: str) -> str:
        # 只做最低要求：纯数字/纯字母太容易被撞库扫到（计划 5.3）
        if value.isdigit() or value.isalpha():
            raise ValueError("密码需同时包含字母和数字")
        return value


class LoginIn(BaseModel):
    phone: str = Field(pattern=_PHONE_PATTERN)
    password: str = Field(min_length=1, max_length=64)


class UserOut(BaseModel):
    id: int
    phone: str  # 已脱敏
    nickname: str


class TokenOut(BaseModel):
    token: str
    expiresAt: datetime
    user: UserOut

"""口令散列与 JWT（计划 2.1：PyJWT + stdlib scrypt，不引 passlib）。

口令格式：``scrypt$n=16384,r=8,p=1$<salt_hex>$<hash_hex>``
- 参数写进串里，未来调强度可平滑兼容旧口令（verify 时按串内参数校验）。
- 不做可逆存储，任何日志都不得输出 hash 正文。
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt

from app.core.config import get_settings
from app.core.errors import UnauthenticatedError

_ALGO = "scrypt"
_N = 2**14
_R = 8
_P = 1
_SALT_BYTES = 16
_KEY_LEN = 32

# scrypt 的 n 必须是 2 的幂；16384 约 16MB 内存、单次 ~60ms，够用且不明显拖慢登录
_MAXMEM = 64 * 1024 * 1024


def hash_password(password: str) -> str:
    """生成口令散列。同一口令每次结果不同（随机 salt）。"""
    if not password:
        raise ValueError("password must not be empty")
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = hashlib.scrypt(
        password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=_KEY_LEN, maxmem=_MAXMEM
    )
    return f"{_ALGO}$n={_N},r={_R},p={_P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """常量时间校验；格式异常一律当失败，不抛业务异常（避免账号探测）。"""
    try:
        algo, params, salt_hex, hash_hex = stored.split("$")
        if algo != _ALGO:
            return False
        kv = dict(item.split("=") for item in params.split(","))
        expected = bytes.fromhex(hash_hex)
        digest = hashlib.scrypt(
            password.encode(),
            salt=bytes.fromhex(salt_hex),
            n=int(kv["n"]),
            r=int(kv["r"]),
            p=int(kv["p"]),
            dklen=len(expected),
            maxmem=_MAXMEM,
        )
    except (ValueError, KeyError):
        return False
    return hmac.compare_digest(digest, expected)


def create_access_token(user_id: int) -> tuple[str, datetime]:
    """签发 JWT，返回 (token, 过期时间 UTC)。"""
    settings = get_settings()
    expires_at = datetime.now(UTC) + timedelta(minutes=settings.jwt_expire_minutes)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "iat": int(datetime.now(UTC).timestamp()),
        "exp": int(expires_at.timestamp()),
        "typ": "access",
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, expires_at


def decode_access_token(token: str) -> int:
    """解析 JWT 并返回 user_id；任何失败都转 401，不暴露具体原因。"""
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        if payload.get("typ") != "access":
            raise UnauthenticatedError("登录状态无效，请重新登录")
        return int(payload["sub"])
    except jwt.ExpiredSignatureError as exc:
        raise UnauthenticatedError("登录已过期，请重新登录") from exc
    except (jwt.InvalidTokenError, KeyError, TypeError, ValueError) as exc:
        raise UnauthenticatedError("登录状态无效，请重新登录") from exc


def mask_phone(phone: str) -> str:
    """手机号脱敏：138****0001。接口与日志一律输出这一形态。"""
    if len(phone) < 7:
        return "***"
    return f"{phone[:3]}****{phone[-4:]}"

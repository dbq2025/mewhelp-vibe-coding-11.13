"""口令散列与 JWT 的单元测试（不碰数据库）。"""

from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.core.config import get_settings
from app.core.errors import UnauthenticatedError
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    mask_phone,
    verify_password,
)


def test_hash_is_salted_and_verifiable() -> None:
    first = hash_password("Test123456")
    second = hash_password("Test123456")
    assert first != second, "同一口令两次散列必须不同（随机 salt）"
    assert "Test123456" not in first
    assert verify_password("Test123456", first)
    assert verify_password("Test123456", second)


def test_verify_rejects_wrong_password_and_bad_hash() -> None:
    stored = hash_password("Test123456")
    assert not verify_password("Test123457", stored)
    assert not verify_password("Test123456", "bcrypt$whatever")
    assert not verify_password("Test123456", "")


def test_token_roundtrip() -> None:
    token, expires_at = create_access_token(42)
    assert expires_at > datetime.now(UTC)
    assert decode_access_token(token) == 42


def test_expired_token_raises_unauthenticated() -> None:
    settings = get_settings()
    payload = {
        "sub": "7",
        "typ": "access",
        "exp": int((datetime.now(UTC) - timedelta(minutes=1)).timestamp()),
    }
    expired = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    with pytest.raises(UnauthenticatedError):
        decode_access_token(expired)


def test_token_signed_with_other_secret_rejected() -> None:
    payload = {
        "sub": "1",
        "typ": "access",
        "exp": int((datetime.now(UTC) + timedelta(hours=1)).timestamp()),
    }
    forged = jwt.encode(payload, "not-the-real-secret", algorithm="HS256")
    with pytest.raises(UnauthenticatedError):
        decode_access_token(forged)


def test_mask_phone_keeps_only_tail() -> None:
    assert mask_phone("13800000001") == "138****0001"
    assert mask_phone("123") == "***"

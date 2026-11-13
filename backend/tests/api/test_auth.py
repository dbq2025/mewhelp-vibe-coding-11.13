"""账号接口测试：注册、登录、鉴权失败路径。

测试会真的往库里写用户，所以每个用例结束按手机号回收（见 `_cleanup`），
否则跑几十次后 users 表会堆一堆测试账号，seed 的行数断言也不再可信。
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import delete

from app.infra.db.models.user import User
from app.infra.db.session import SessionFactory

_created_phones: list[str] = []


def _random_phone() -> str:
    # 139 + 8 位随机数字，避免多次运行撞唯一索引
    return "139" + str(uuid.uuid4().int)[:8]


@pytest.fixture(autouse=True)
async def _cleanup() -> None:
    yield
    if not _created_phones:
        return
    async with SessionFactory() as session:
        await session.execute(delete(User).where(User.phone.in_(_created_phones)))
        await session.commit()
    _created_phones.clear()


async def test_register_then_me(client: AsyncClient) -> None:
    phone = _random_phone()
    _created_phones.append(phone)
    response = await client.post(
        "/api/v1/auth/register",
        json={"phone": phone, "password": "Abc123456", "nickname": "新用户"},
    )
    assert response.status_code == 201, response.text
    data = response.json()["data"]
    assert data["user"]["phone"] == f"{phone[:3]}****{phone[-4:]}", "手机号必须脱敏"
    assert data["token"]

    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {data['token']}"})
    assert me.status_code == 200
    assert me.json()["data"]["nickname"] == "新用户"


async def test_duplicate_phone_rejected(client: AsyncClient) -> None:
    phone = _random_phone()
    _created_phones.append(phone)
    payload = {"phone": phone, "password": "Abc123456", "nickname": ""}
    first = await client.post("/api/v1/auth/register", json=payload)
    assert first.status_code == 201
    second = await client.post("/api/v1/auth/register", json=payload)
    assert second.status_code == 400
    assert second.json()["code"] == 1001


async def test_weak_password_rejected(client: AsyncClient) -> None:
    phone = _random_phone()
    _created_phones.append(phone)  # 校验失败不会建号，但登记了也不会有副作用
    response = await client.post(
        "/api/v1/auth/register",
        json={"phone": phone, "password": "12345678", "nickname": ""},
    )
    assert response.status_code == 400
    assert response.json()["code"] == 1001


async def test_login_wrong_password(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/login", json={"phone": "13800000001", "password": "wrong-password"}
    )
    assert response.status_code == 401
    assert response.json()["code"] == 2001


async def test_me_without_token(client: AsyncClient) -> None:
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 401
    assert response.json()["code"] == 2001


async def test_me_with_invalid_token(client: AsyncClient) -> None:
    response = await client.get("/api/v1/auth/me", headers={"Authorization": "Bearer not-a-jwt"})
    assert response.status_code == 401
    assert response.json()["code"] == 2001

"""订单接口与越权拦截测试（P1 验收第 3 条的核心用例）。

断言三件事：
1. 越权/不存在/尾号错都返回 2003，不泄漏"订单是否存在"；
2. 每次拒绝都在 `audit_events` 落一条 denied；
3. 正常路径能拿到明细与物流。
"""

from httpx import AsyncClient
from sqlalchemy import func, select

from app.infra.db.models.ops import AuditEvent
from app.infra.db.session import SessionFactory

# seed 里 A 的单：20261101001-014；B 的单：20261101023-030
A_ORDER = "20261101001"
A_SHIPPED_ORDER = "20261101002"
B_ORDER = "20261101023"


async def _audit_count(target: str) -> int:
    async with SessionFactory() as session:
        return int(
            await session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.target == target, AuditEvent.result == "denied")
            )
            or 0
        )


async def test_my_orders_requires_login(client: AsyncClient) -> None:
    response = await client.get("/api/v1/orders")
    assert response.status_code == 401
    assert response.json()["code"] == 2001


async def test_my_orders_only_returns_own(auth_client: AsyncClient) -> None:
    response = await auth_client.get("/api/v1/orders", params={"limit": 100})
    assert response.status_code == 200
    items = response.json()["data"]["items"]
    assert items
    assert all(item["orderNo"] <= "20261101014" for item in items)
    assert all(item["itemCount"] >= 1 for item in items)


async def test_own_order_detail_has_items_and_no_full_phone(auth_client: AsyncClient) -> None:
    response = await auth_client.get(f"/api/v1/orders/{A_ORDER}")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["orderNo"] == A_ORDER
    assert data["items"]
    assert len(data["receiverPhoneTail"]) == 4
    body = response.text
    assert "13800000001" not in body, "响应里不允许出现完整手机号"


async def test_cross_user_order_denied_and_audited(auth_client: AsyncClient) -> None:
    before = await _audit_count(B_ORDER)
    response = await auth_client.get(f"/api/v1/orders/{B_ORDER}")
    assert response.status_code == 403
    assert response.json()["code"] == 2003
    assert "不存在" in response.json()["message"]
    after = await _audit_count(B_ORDER)
    assert after == before + 1, "越权必须落审计"


async def test_unknown_order_same_code_as_forbidden(auth_client: AsyncClient) -> None:
    missing = await auth_client.get("/api/v1/orders/202699999999")
    forbidden = await auth_client.get(f"/api/v1/orders/{B_ORDER}")
    assert missing.status_code == forbidden.status_code == 403
    assert missing.json()["code"] == forbidden.json()["code"] == 2003


async def test_guest_can_read_with_correct_phone_tail(client: AsyncClient) -> None:
    response = await client.get(f"/api/v1/orders/{B_ORDER}", params={"phoneTail": "0002"})
    assert response.status_code == 200
    assert response.json()["data"]["orderNo"] == B_ORDER


async def test_guest_wrong_or_missing_tail_denied(client: AsyncClient) -> None:
    before = await _audit_count(B_ORDER)
    wrong = await client.get(f"/api/v1/orders/{B_ORDER}", params={"phoneTail": "9999"})
    missing = await client.get(f"/api/v1/orders/{B_ORDER}")
    assert wrong.status_code == 403 and wrong.json()["code"] == 2003
    assert missing.status_code == 403 and missing.json()["code"] == 2003
    assert await _audit_count(B_ORDER) == before + 2


async def test_phone_tail_must_be_four_digits(client: AsyncClient) -> None:
    response = await client.get(f"/api/v1/orders/{B_ORDER}", params={"phoneTail": "abc"})
    assert response.status_code == 400
    assert response.json()["code"] == 1001


async def test_shipment_returns_tracking(auth_client: AsyncClient) -> None:
    response = await auth_client.get(f"/api/v1/orders/{A_SHIPPED_ORDER}/shipment")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data is not None
    assert data["carrier"]
    assert data["trackingNo"]
    assert data["events"], "已发货订单必须有轨迹节点"


async def test_shipment_denied_cross_user(auth_client: AsyncClient) -> None:
    response = await auth_client.get(f"/api/v1/orders/{B_ORDER}/shipment")
    assert response.status_code == 403
    assert response.json()["code"] == 2003

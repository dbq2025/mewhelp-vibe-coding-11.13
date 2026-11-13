"""健康检查集成测试：真实打库 + 真实 pgvector 探测。

这些用例的价值是"起了服务到底连不连得上库"，所以不打桩。
"""

from httpx import AsyncClient

from app.core.trace import TRACE_HEADER


async def test_health_db_and_vector_are_ok(client: AsyncClient) -> None:
    resp = await client.get("/health")

    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    assert body["data"]["db"] == "ok"
    assert body["data"]["vector"] == "ok"
    assert body["data"]["status"] == "ok"
    assert body["data"]["vectorVersion"] is not None


async def test_health_envelope_carries_trace_id(client: AsyncClient) -> None:
    resp = await client.get("/health")

    body = resp.json()
    assert body["traceId"], "envelope 必须带 traceId"
    assert resp.headers[TRACE_HEADER] == body["traceId"]


async def test_health_reuses_incoming_trace_id(client: AsyncClient) -> None:
    resp = await client.get("/health", headers={TRACE_HEADER: "abc123def4567890"})

    assert resp.json()["traceId"] == "abc123def4567890"
    assert resp.headers[TRACE_HEADER] == "abc123def4567890"


async def test_meta_exposes_api_prefix(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/meta")

    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["apiPrefix"] == "/api/v1"
    assert body["data"]["name"] == "ecom-copilot"


async def test_unknown_route_returns_envelope_not_html(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/not-exists")

    assert resp.status_code == 404
    body = resp.json()
    assert body["code"] == 2004
    assert "traceId" in body

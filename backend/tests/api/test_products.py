"""商品接口测试：价格过滤、分页 cursor、详情 404、下架商品不可见。"""

from httpx import AsyncClient


async def test_price_max_filter(client: AsyncClient) -> None:
    response = await client.get("/api/v1/products", params={"priceMax": 100000, "limit": 100})
    assert response.status_code == 200
    items = response.json()["data"]["items"]
    assert items, "seed 里应有 1000 元以内商品"
    assert all(item["priceCents"] <= 100000 for item in items)
    assert all(item["status"] == "on_sale" for item in items)


async def test_price_range_filter(client: AsyncClient) -> None:
    response = await client.get(
        "/api/v1/products", params={"priceMin": 30000, "priceMax": 60000, "limit": 100}
    )
    items = response.json()["data"]["items"]
    assert items
    assert all(30000 <= item["priceCents"] <= 60000 for item in items)


async def test_invalid_range_rejected(client: AsyncClient) -> None:
    response = await client.get("/api/v1/products", params={"priceMin": 200000, "priceMax": 100})
    assert response.status_code == 400
    assert response.json()["code"] == 1001


async def test_category_filter_by_name_and_id(client: AsyncClient) -> None:
    by_name = await client.get("/api/v1/products", params={"category": "降噪耳机", "limit": 100})
    assert by_name.status_code == 200
    items = by_name.json()["data"]["items"]
    assert items
    assert all(item["categoryName"] == "降噪耳机" for item in items)

    category_id = items[0]["categoryId"]
    by_id = await client.get(
        "/api/v1/products", params={"category": str(category_id), "limit": 100}
    )
    assert {item["id"] for item in by_id.json()["data"]["items"]} == {item["id"] for item in items}


async def test_cursor_pagination_has_no_overlap(client: AsyncClient) -> None:
    page1 = await client.get("/api/v1/products", params={"limit": 5, "sort": "price_asc"})
    data1 = page1.json()["data"]
    assert len(data1["items"]) == 5
    assert data1["page"]["hasMore"] is True

    page2 = await client.get(
        "/api/v1/products",
        params={"limit": 5, "sort": "price_asc", "cursor": data1["page"]["nextCursor"]},
    )
    data2 = page2.json()["data"]
    ids1 = {item["id"] for item in data1["items"]}
    ids2 = {item["id"] for item in data2["items"]}
    assert not (ids1 & ids2), "两页不能重复"
    prices1 = [item["priceCents"] for item in data1["items"]]
    prices2 = [item["priceCents"] for item in data2["items"]]
    assert prices1[-1] <= prices2[0], "价格升序必须跨页保持"


async def test_bad_cursor_rejected(client: AsyncClient) -> None:
    response = await client.get("/api/v1/products", params={"cursor": "not-base64"})
    assert response.status_code == 400
    assert response.json()["code"] == 1001


async def test_product_detail_and_404(client: AsyncClient) -> None:
    listing = await client.get("/api/v1/products", params={"limit": 1})
    product_id = listing.json()["data"]["items"][0]["id"]
    detail = await client.get(f"/api/v1/products/{product_id}")
    assert detail.status_code == 200
    data = detail.json()["data"]
    assert data["id"] == product_id
    assert data["description"]
    assert isinstance(data["attrs"], dict)

    missing = await client.get("/api/v1/products/999999")
    assert missing.status_code == 404
    assert missing.json()["code"] == 2004


async def test_offshelf_product_hidden_from_list(client: AsyncClient) -> None:
    response = await client.get("/api/v1/products", params={"q": "Studio Max", "limit": 100})
    items = response.json()["data"]["items"]
    assert all(item["name"] != "极光 Studio Max 头戴旗舰" for item in items)

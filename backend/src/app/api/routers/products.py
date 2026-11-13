"""商品路由（api.md §2.5）：列表 + 详情，只读、无需登录。"""

from typing import Annotated, Literal

from fastapi import APIRouter, Query

from app.api.schemas.common import ApiResponse, PageData, PageMeta, ok
from app.api.schemas.product import ProductBrief, ProductDetail
from app.core.deps import DbSession
from app.core.errors import NotFoundError
from app.domain.services import catalog

router = APIRouter(prefix="/products", tags=["products"])


@router.get("", response_model=ApiResponse[PageData[ProductBrief]], summary="商品列表")
async def list_products(
    session: DbSession,
    q: Annotated[str | None, Query(max_length=50, description="关键词，匹配名称/品牌/SKU")] = None,
    category: Annotated[str | None, Query(max_length=50, description="类目名或类目 id")] = None,
    brand: Annotated[str | None, Query(max_length=50)] = None,
    price_min: Annotated[
        int | None, Query(alias="priceMin", ge=0, description="价格下限（分）")
    ] = None,
    price_max: Annotated[
        int | None, Query(alias="priceMax", ge=0, description="价格上限（分）")
    ] = None,
    sort: Annotated[
        Literal["recommend", "price_asc", "price_desc", "newest"], Query()
    ] = "recommend",
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query(max_length=128)] = None,
) -> ApiResponse[PageData[ProductBrief]]:
    rows, next_cursor, has_more = await catalog.list_products(
        session,
        q=q,
        category=category,
        brand=brand,
        price_min=price_min,
        price_max=price_max,
        sort=sort,
        limit=limit,
        cursor=cursor,
    )
    items = [
        ProductBrief(
            id=product.id,
            sku=product.sku,
            name=product.name,
            categoryId=product.category_id,
            categoryName=category_name,
            brand=product.brand,
            priceCents=product.price_cents,
            stock=product.stock,
            status=product.status,
            imageUrl=product.image_url,
        )
        for product, category_name in rows
    ]
    return ok(
        PageData[ProductBrief](items=items, page=PageMeta(nextCursor=next_cursor, hasMore=has_more))
    )


@router.get("/{product_id}", response_model=ApiResponse[ProductDetail], summary="商品详情")
async def get_product(product_id: int, session: DbSession) -> ApiResponse[ProductDetail]:
    row = await catalog.get_product(session, product_id)
    if row is None:
        raise NotFoundError("商品不存在")
    product, category_name = row
    return ok(
        ProductDetail(
            id=product.id,
            sku=product.sku,
            name=product.name,
            categoryId=product.category_id,
            categoryName=category_name,
            brand=product.brand,
            priceCents=product.price_cents,
            stock=product.stock,
            status=product.status,
            imageUrl=product.image_url,
            description=product.description,
            attrs=product.attrs or {},
        )
    )

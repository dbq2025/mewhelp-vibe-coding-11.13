"""商品接口的请求/响应体（api.md §2.5）。金额一律整数分。"""

from typing import Any

from pydantic import BaseModel, Field


class ProductBrief(BaseModel):
    id: int
    sku: str
    name: str
    categoryId: int
    categoryName: str
    brand: str
    priceCents: int
    stock: int
    status: str
    imageUrl: str


class ProductDetail(ProductBrief):
    description: str = ""
    attrs: dict[str, Any] = Field(default_factory=dict)

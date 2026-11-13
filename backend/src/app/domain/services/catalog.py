"""商品检索服务（只读）。

分页用 cursor 而非 offset（api.md §1.3）：深翻页时 offset 会全表扫描，
且新商品插入会导致"第二页重复第一条"。cursor 存 (排序键, id) 二元组，
排序键相同再按 id 兜底，保证严格单调、不重不漏。

cursor 对客户端不透明：base64("price:100:id:37") 形态，解析失败按 1001 处理。
"""

from __future__ import annotations

import base64
import binascii
from datetime import datetime
from typing import Literal

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import InvalidParamError
from app.infra.db.models.catalog import Category, Product

SortKey = Literal["recommend", "price_asc", "price_desc", "newest"]

_SORT_COLUMNS: dict[str, str] = {
    "recommend": "id",
    "price_asc": "price_cents",
    "price_desc": "price_cents",
    "newest": "created_at",
}


def encode_cursor(sort: str, sort_value: object, row_id: int) -> str:
    raw = f"{sort}|{sort_value}|{row_id}".encode()
    return base64.urlsafe_b64encode(raw).decode()


def decode_cursor(cursor: str, sort: str) -> tuple[str, int]:
    """返回 (排序键值原始串, 行 id)。格式不符直接 1001，不发模糊查询。"""
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        cur_sort, sort_value, row_id = raw.rsplit("|", 2)
        if cur_sort != sort:
            raise InvalidParamError("cursor 与 sort 不匹配，请重新从第一页开始")
        return sort_value, int(row_id)
    except (binascii.Error, UnicodeDecodeError, ValueError) as exc:
        raise InvalidParamError("cursor 不合法") from exc


def _apply_filters(
    stmt: Select[tuple[Product, str]],
    *,
    q: str | None,
    category: str | None,
    brand: str | None,
    price_min: int | None,
    price_max: int | None,
) -> Select[tuple[Product, str]]:
    # 默认只看在售商品；下架商品留给详情页（可能带"已下架"提示）
    stmt = stmt.where(Product.status == "on_sale")
    if q:
        # ILIKE + pg_trgm 索引：40 条数据量下无所谓，但口径与生产一致
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(Product.name.ilike(like), Product.brand.ilike(like), Product.sku.ilike(like))
        )
    if brand:
        stmt = stmt.where(Product.brand == brand)
    if price_min is not None:
        stmt = stmt.where(Product.price_cents >= price_min)
    if price_max is not None:
        stmt = stmt.where(Product.price_cents <= price_max)
    if category:
        cond = Category.name == category
        if category.isdigit():
            cond = or_(cond, Category.id == int(category))
        stmt = stmt.where(cond)
    return stmt


async def list_products(
    session: AsyncSession,
    *,
    q: str | None = None,
    category: str | None = None,
    brand: str | None = None,
    price_min: int | None = None,
    price_max: int | None = None,
    sort: SortKey = "recommend",
    limit: int = 20,
    cursor: str | None = None,
) -> tuple[list[tuple[Product, str]], str | None, bool]:
    """返回 ([(商品, 类目名)], next_cursor, has_more)。"""
    if price_min is not None and price_max is not None and price_min > price_max:
        raise InvalidParamError("priceMin 不能大于 priceMax")
    limit = max(1, min(limit, 100))

    stmt = select(Product, Category.name).join(Category, Category.id == Product.category_id)
    stmt = _apply_filters(
        stmt,
        q=q,
        category=category,
        brand=brand,
        price_min=price_min,
        price_max=price_max,
    )

    sort_col_name = _SORT_COLUMNS[sort]
    sort_col = getattr(Product, sort_col_name)
    descending = sort in ("price_desc", "newest")

    if cursor:
        sort_value, row_id = decode_cursor(cursor, sort)
        typed_value: object = row_id if sort_col_name == "id" else _coerce(sort_value, sort)
        if descending:
            stmt = stmt.where(
                or_(
                    sort_col < typed_value,
                    (sort_col == typed_value) & (Product.id < row_id),
                )
            )
        else:
            stmt = stmt.where(
                or_(
                    sort_col > typed_value,
                    (sort_col == typed_value) & (Product.id > row_id),
                )
            )

    if descending:
        stmt = stmt.order_by(sort_col.desc(), Product.id.desc())
    else:
        stmt = stmt.order_by(sort_col.asc(), Product.id.asc())

    # 多取一条判断 hasMore，避免额外 count 查询
    rows = list((await session.execute(stmt.limit(limit + 1))).all())
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = None
    if has_more and rows:
        last_product = rows[-1][0]
        next_cursor = encode_cursor(sort, getattr(last_product, sort_col_name), last_product.id)
    return [(row[0], row[1]) for row in rows], next_cursor, has_more


def _coerce(sort_value: str, sort: str) -> object:
    if sort in ("price_asc", "price_desc"):
        try:
            return int(sort_value)
        except ValueError as exc:
            raise InvalidParamError("cursor 不合法") from exc
    if sort == "newest":
        try:
            return datetime.fromisoformat(sort_value)
        except ValueError as exc:
            raise InvalidParamError("cursor 不合法") from exc
    return sort_value


async def get_product(session: AsyncSession, product_id: int) -> tuple[Product, str] | None:
    row = (
        await session.execute(
            select(Product, Category.name)
            .join(Category, Category.id == Product.category_id)
            .where(Product.id == product_id)
        )
    ).first()
    return (row[0], row[1]) if row else None


async def count_on_sale(session: AsyncSession) -> int:
    return int(
        await session.scalar(
            select(func.count()).select_from(Product).where(Product.status == "on_sale")
        )
        or 0
    )

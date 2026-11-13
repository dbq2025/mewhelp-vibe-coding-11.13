"""演示数据（计划 5.4）：40 商品 / 8 分类 / 3 品牌 / 30 订单 / 12 物流 / 3 账号。

设计原则：
1. **幂等**：按业务键（手机号 / SKU / 订单号 / 运单）upsert，重复执行行数不变；
2. **可测越权**：显式区分 A（主测账号）、C（第二用户）、B（"他人账号"），
   订单分散到三个账号，越权用例直接拿 A 的 token 查 B 的单；
3. **可测区间查询**：商品价格刻意跨 1000 元边界，用来验证 `priceMax` 过滤；
4. **不写真实隐私**：收货手机号只存尾号 4 位，地址脱敏，符合计划 5.1。

用法：
    uv run python scripts/seed.py            # 灌/更新数据
    uv run python scripts/seed.py --check    # 只打行数，不写库
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert

from app.core.security import hash_password
from app.infra.db.models.catalog import Category, Product
from app.infra.db.models.order import AfterSale, Order, OrderItem, Shipment
from app.infra.db.models.user import User
from app.infra.db.session import SessionFactory, dispose_engine

# 三个测试账号的初始口令：只用于本地演示，README 里公开写明
DEMO_PASSWORD = "Test123456"

USERS: list[dict[str, Any]] = [
    {"phone": "13800000001", "nickname": "主测账号A", "tail": "0001"},
    {"phone": "13800000002", "nickname": "他人账号B", "tail": "0002"},
    {"phone": "13800000003", "nickname": "第二用户C", "tail": "0003"},
]

CATEGORIES: list[dict[str, str]] = [
    {"name": "降噪耳机", "path": "/音频/耳机", "desc": "入耳式主动降噪"},
    {"name": "头戴耳机", "path": "/音频/耳机", "desc": "头戴式包耳"},
    {"name": "蓝牙音箱", "path": "/音频/音箱", "desc": "便携与户外"},
    {"name": "充电器", "path": "/配件/充电", "desc": "氮化镓与快充头"},
    {"name": "数据线", "path": "/配件/线材", "desc": "快充与编织线"},
    {"name": "智能手表", "path": "/穿戴/手表", "desc": "运动与健康监测"},
    {"name": "机械键盘", "path": "/外设/键盘", "desc": "热插拔与三模"},
    {"name": "手机壳", "path": "/配件/保护", "desc": "磁吸与防摔"},
]

_ATTRS: dict[str, dict[str, Any]] = {
    "降噪耳机": {
        "降噪深度": "42dB",
        "续航": "30小时",
        "蓝牙": "5.3",
        "防水": "IPX4",
        "多设备连接": True,
    },
    "头戴耳机": {
        "降噪深度": "38dB",
        "续航": "40小时",
        "蓝牙": "5.3",
        "佩戴": "包耳式",
        "多设备连接": True,
    },
    "蓝牙音箱": {"功率": "20W", "续航": "12小时", "防水": "IPX7", "蓝牙": "5.3"},
    "充电器": {"功率": "65W", "接口": "2C1A", "协议": "PD3.0/QC4+", "折叠插脚": True},
    "数据线": {"长度": "1.5m", "功率": "100W", "接口": "USB-C to USB-C", "材质": "编织"},
    "智能手表": {"屏幕": "1.43英寸AMOLED", "续航": "14天", "防水": "5ATM", "GPS": True},
    "机械键盘": {"轴体": "线性轴", "配列": "68键", "连接": "三模", "热插拔": True},
    "手机壳": {"材质": "TPU+PC", "磁吸": True, "适配": "iPhone 16"},
}

# (sku, 名称, 分类, 品牌, 价格分, 库存, 状态)
_PRODUCT_ROWS: list[tuple[str, str, str, str, int, int, str]] = [
    ("SG-AIR-PRO", "声谷 Air Pro 主动降噪耳机", "降噪耳机", "声谷", 69900, 120, "on_sale"),
    ("SG-AIR-LITE", "声谷 Air Lite 半入耳耳机", "降噪耳机", "声谷", 29900, 200, "on_sale"),
    ("AG-BUDS3", "极光 Buds 3 降噪耳机", "降噪耳机", "极光", 89900, 80, "on_sale"),
    ("AG-BUDS-SE", "极光 Buds SE 蓝牙耳机", "降噪耳机", "极光", 25900, 300, "on_sale"),
    ("YQ-QUIET2", "云雀 Quiet 2 降噪耳机", "降噪耳机", "云雀", 45900, 150, "on_sale"),
    ("SG-AIR-MAX", "声谷 Air Max 旗舰降噪耳机", "降噪耳机", "声谷", 129900, 40, "on_sale"),
    ("AG-BUDS-PRO", "极光 Buds Pro 双单元降噪耳机", "降噪耳机", "极光", 109900, 35, "on_sale"),
    ("YQ-QUIET-AIR", "云雀 Quiet Air 轻量降噪耳机", "降噪耳机", "云雀", 34900, 180, "on_sale"),
    ("SG-SPORT", "声谷 Sport 运动防水耳机", "降噪耳机", "声谷", 39900, 90, "on_sale"),
    ("YQ-OPEN", "云雀 Open 开放式耳机", "降噪耳机", "云雀", 54900, 60, "on_sale"),
    ("SG-H1", "声谷 H1 头戴降噪耳机", "头戴耳机", "声谷", 159900, 25, "on_sale"),
    ("AG-STUDIO", "极光 Studio 头戴耳机", "头戴耳机", "极光", 99900, 45, "on_sale"),
    ("YQ-H2", "云雀 H2 头戴耳机", "头戴耳机", "云雀", 59900, 70, "on_sale"),
    ("SG-H1-LITE", "声谷 H1 Lite 头戴耳机", "头戴耳机", "声谷", 79900, 55, "on_sale"),
    ("AG-STUDIO-MAX", "极光 Studio Max 头戴旗舰", "头戴耳机", "极光", 219900, 0, "off_shelf"),
    ("SG-CUBE", "声谷 Cube 便携蓝牙音箱", "蓝牙音箱", "声谷", 19900, 220, "on_sale"),
    ("AG-BOOM", "极光 Boom 户外音箱", "蓝牙音箱", "极光", 39900, 110, "on_sale"),
    ("YQ-MINI", "云雀 Mini 桌面音箱", "蓝牙音箱", "云雀", 12900, 260, "on_sale"),
    ("SG-CUBE-PRO", "声谷 Cube Pro 立体声音箱", "蓝牙音箱", "声谷", 49900, 75, "on_sale"),
    ("AG-BOOM-MAX", "极光 Boom Max 大功率音箱", "蓝牙音箱", "极光", 89900, 30, "on_sale"),
    ("SG-GA65", "声谷 65W 氮化镓充电器", "充电器", "声谷", 12900, 400, "on_sale"),
    ("AG-PD30", "极光 30W 快充充电头", "充电器", "极光", 6900, 500, "on_sale"),
    ("YQ-PD20", "云雀 20W 充电头", "充电器", "云雀", 4900, 600, "on_sale"),
    ("SG-GA100", "声谷 100W 多口氮化镓充电器", "充电器", "声谷", 24900, 150, "on_sale"),
    ("AG-GA65D", "极光 65W 双口充电器", "充电器", "极光", 15900, 180, "on_sale"),
    ("YQ-GA45", "云雀 45W 氮化镓充电器", "充电器", "云雀", 9900, 220, "on_sale"),
    ("SG-CC15", "声谷 C to C 1.5m 编织数据线", "数据线", "声谷", 3900, 800, "on_sale"),
    ("AG-LT10", "极光 Lightning 1m 数据线", "数据线", "极光", 4900, 700, "on_sale"),
    ("YQ-CL10", "云雀 C to Lightning 1m 线", "数据线", "云雀", 4500, 650, "on_sale"),
    ("SG-CC20", "声谷 100W 2m 快充数据线", "数据线", "声谷", 5900, 520, "on_sale"),
    ("AG-3IN1", "极光 三合一数据线", "数据线", "极光", 6900, 0, "off_shelf"),
    ("SG-WATCH-S", "声谷 Watch S 智能手表", "智能手表", "声谷", 89900, 90, "on_sale"),
    ("AG-WATCH2", "极光 Watch 2 运动手表", "智能手表", "极光", 129900, 45, "on_sale"),
    ("YQ-WATCH-LITE", "云雀 Watch Lite 轻智能手表", "智能手表", "云雀", 49900, 130, "on_sale"),
    ("SG-WATCH-PRO", "声谷 Watch S Pro 旗舰手表", "智能手表", "声谷", 159900, 22, "on_sale"),
    ("AG-WATCH-KIDS", "极光 Watch Kids 儿童手表", "智能手表", "极光", 69900, 100, "on_sale"),
    ("SG-K68", "声谷 K68 机械键盘", "机械键盘", "声谷", 39900, 85, "on_sale"),
    ("AG-K87", "极光 K87 热插拔键盘", "机械键盘", "极光", 54900, 60, "on_sale"),
    ("YQ-K61", "云雀 K61 客制化键盘", "机械键盘", "云雀", 32900, 95, "on_sale"),
    ("YQ-CASE-MAG", "云雀 磁吸透明手机壳", "手机壳", "云雀", 7900, 900, "on_sale"),
]

_SELLING_POINTS: dict[str, str] = {
    "降噪耳机": "支持主动降噪与通透模式，双设备无缝切换，适合通勤与办公。",
    "头戴耳机": "包耳式佩戴，长时间使用不压耳，支持有线无线双模式。",
    "蓝牙音箱": "支持 IPX7 防水与立体声串联，户外露营可用。",
    "充电器": "支持 PD 快充协议，可为手机、平板、轻薄本供电，折叠插脚便于携带。",
    "数据线": "编织线身抗弯折，支持大功率快充与数据传输。",
    "智能手表": "支持心率、血氧与睡眠监测，内置多种运动模式。",
    "机械键盘": "支持三模连接与热插拔换轴，适配 Windows 与 macOS。",
    "手机壳": "磁吸对位精准，支持无线充电，四角气囊防摔。",
}

_ORDER_STATUSES = [
    "pending_pay",
    "pending_ship",
    "shipped",
    "delivered",
    "refunding",
    "closed",
]

_CARRIERS = ["顺丰速运", "京东物流", "中通快递"]


def _product_description(name: str, category: str, brand: str) -> str:
    return (
        f"{name}。{brand}出品，{_SELLING_POINTS[category]}"
        "外观简洁，配件齐全，随箱附带快速入门指南。"
    )


def _order_time(index: int) -> datetime:
    base = datetime(2026, 11, 1, 9, 30, tzinfo=UTC)
    return base + timedelta(days=index % 13, hours=(index * 5) % 11)


async def _seed_users(session: Any) -> dict[str, User]:
    users: dict[str, User] = {}
    for item in USERS:
        stmt = (
            insert(User)
            .values(
                phone=item["phone"],
                nickname=item["nickname"],
                password_hash=hash_password(DEMO_PASSWORD),
            )
            .on_conflict_do_update(
                index_elements=[User.phone],
                set_={"nickname": item["nickname"]},
            )
        )
        await session.execute(stmt)
        user = await session.scalar(select(User).where(User.phone == item["phone"]))
        assert user is not None
        users[item["nickname"]] = user
    return users


async def _seed_categories(session: Any) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for item in CATEGORIES:
        existing = await session.scalar(
            select(Category).where(Category.name == item["name"], Category.path == item["path"])
        )
        if existing is None:
            existing = Category(name=item["name"], path=item["path"])
            session.add(existing)
            await session.flush()
        mapping[item["name"]] = existing.id
    return mapping


async def _seed_products(session: Any, categories: dict[str, int]) -> dict[str, Product]:
    products: dict[str, Product] = {}
    for sku, name, category, brand, price_cents, stock, status in _PRODUCT_ROWS:
        attrs = dict(_ATTRS[category])
        values = {
            "sku": sku,
            "name": name,
            "category_id": categories[category],
            "brand": brand,
            "price_cents": price_cents,
            "stock": stock,
            "status": status,
            "attrs": attrs,
            "description": _product_description(name, category, brand),
            "image_url": f"https://cdn.example.com/products/{sku.lower()}.jpg",
        }
        stmt = (
            insert(Product)
            .values(**values)
            .on_conflict_do_update(
                index_elements=[Product.sku],
                set_={k: v for k, v in values.items() if k != "sku"},
            )
        )
        await session.execute(stmt)
        product = await session.scalar(select(Product).where(Product.sku == sku))
        assert product is not None
        products[sku] = product
    return products


def _plan_orders(products: dict[str, Product], users: dict[str, User]) -> list[dict[str, Any]]:
    """确定性生成 30 单：A 14 单、C 8 单、B 8 单（B 用于越权测试）。"""
    skus = list(products)
    owners = ["主测账号A"] * 14 + ["第二用户C"] * 8 + ["他人账号B"] * 8
    tails = {item["nickname"]: item["tail"] for item in USERS}
    planned: list[dict[str, Any]] = []
    for i, nickname in enumerate(owners, start=1):
        user = users[nickname]
        status = _ORDER_STATUSES[i % len(_ORDER_STATUSES)]
        picked = [products[skus[(i * 3) % len(skus)]]]
        if i % 3 == 0:
            picked.append(products[skus[(i * 7 + 5) % len(skus)]])
        items = [
            {
                "product_id": product.id,
                "sku_snapshot": product.sku,
                "name_snapshot": product.name,
                "qty": 2 if i % 5 == 0 else 1,
                "unit_price_cents": product.price_cents,
            }
            for product in picked
        ]
        total = sum(item["qty"] * item["unit_price_cents"] for item in items)
        created_at = _order_time(i)
        planned.append(
            {
                "order_no": f"20261101{i:03d}",
                "user_id": user.id,
                "status": status,
                "total_cents": total,
                "receiver_phone_tail": tails[nickname],
                "receiver_address_masked": "浙江省杭州市西湖区文三路 *** 号 **** 室",
                "created_at": created_at,
                "paid_at": None if status == "pending_pay" else created_at + timedelta(minutes=3),
                "items": items,
            }
        )
    return planned


async def _seed_orders(session: Any, planned: list[dict[str, Any]]) -> dict[str, int]:
    order_ids: dict[str, int] = {}
    for plan in planned:
        order_values = {k: v for k, v in plan.items() if k != "items"}
        stmt = (
            insert(Order)
            .values(**order_values)
            .on_conflict_do_update(
                index_elements=[Order.order_no],
                set_={
                    "status": plan["status"],
                    "total_cents": plan["total_cents"],
                    "paid_at": plan["paid_at"],
                },
            )
        )
        await session.execute(stmt)
        order = await session.scalar(select(Order).where(Order.order_no == plan["order_no"]))
        assert order is not None
        order_ids[plan["order_no"]] = order.id

        # 明细整体替换：避免重跑时数量翻倍
        await session.execute(delete(OrderItem).where(OrderItem.order_id == order.id))
        for item in plan["items"]:
            session.add(OrderItem(order_id=order.id, **item))
    return order_ids


async def _seed_shipments(
    session: Any, planned: list[dict[str, Any]], order_ids: dict[str, int]
) -> int:
    shipped = [p for p in planned if p["status"] in {"shipped", "delivered", "refunding"}][:12]
    keep_ids = {order_ids[plan["order_no"]] for plan in shipped}
    stale_ids = [oid for oid in order_ids.values() if oid not in keep_ids]
    if stale_ids:
        # 状态变更后旧的物流记录要清掉，否则重跑会留下"未发货却有运单"的脏数据
        await session.execute(delete(Shipment).where(Shipment.order_id.in_(stale_ids)))
    for index, plan in enumerate(shipped, start=1):
        order_id = order_ids[plan["order_no"]]
        base = plan["created_at"] + timedelta(days=1)
        events = [
            {
                "time": (base).isoformat(),
                "status": "picked_up",
                "desc": "快件已由仓库发出",
            },
            {
                "time": (base + timedelta(hours=8)).isoformat(),
                "status": "in_transit",
                "desc": "快件已到达杭州转运中心",
            },
        ]
        if plan["status"] == "delivered":
            events.append(
                {
                    "time": (base + timedelta(days=2)).isoformat(),
                    "status": "delivered",
                    "desc": "快件已签收，签收人：本人",
                }
            )
        values = {
            "order_id": order_id,
            "carrier": _CARRIERS[index % len(_CARRIERS)],
            "tracking_no": f"{'SF' if index % 3 == 1 else 'JD'}{900000 + index}",
            "status": "delivered" if plan["status"] == "delivered" else "in_transit",
            "events": events,
        }
        stmt = (
            insert(Shipment)
            .values(**values)
            .on_conflict_do_update(index_elements=[Shipment.order_id], set_=values)
        )
        await session.execute(stmt)
    return len(shipped)


async def _seed_after_sales(
    session: Any, planned: list[dict[str, Any]], order_ids: dict[str, int]
) -> int:
    refunding = [p for p in planned if p["status"] == "refunding"][:3]
    for index, plan in enumerate(refunding, start=1):
        values = {
            "ticket_no": f"AS20261101{index:03d}",
            "order_id": order_ids[plan["order_no"]],
            "order_no": plan["order_no"],
            "user_id": plan["user_id"],
            "type": "return",
            "status": "pending",
            "reason": "降噪效果不符合预期，申请退货",
            # 种子单标记来源，便于和"对话/接口真实建的单"区分
            "source": "seed",
        }
        stmt = (
            insert(AfterSale)
            .values(**values)
            .on_conflict_do_nothing(index_elements=[AfterSale.ticket_no])
        )
        await session.execute(stmt)
    return len(refunding)


async def _counts(session: Any) -> dict[str, int]:
    tables = {
        "users": User,
        "categories": Category,
        "products": Product,
        "orders": Order,
        "order_items": OrderItem,
        "shipments": Shipment,
        "after_sales": AfterSale,
    }
    result: dict[str, int] = {}
    for name, model in tables.items():
        result[name] = int(await session.scalar(select(func.count()).select_from(model)) or 0)
    return result


async def seed(*, check_only: bool = False) -> dict[str, int]:
    async with SessionFactory() as session:
        if check_only:
            return await _counts(session)

        users = await _seed_users(session)
        categories = await _seed_categories(session)
        products = await _seed_products(session, categories)
        planned = _plan_orders(products, users)
        order_ids = await _seed_orders(session, planned)
        shipments = await _seed_shipments(session, planned, order_ids)
        after_sales = await _seed_after_sales(session, planned, order_ids)
        await session.commit()

        counts = await _counts(session)
        counts["_shipments_seeded"] = shipments
        counts["_after_sales_seeded"] = after_sales
        return counts


def main() -> None:
    parser = argparse.ArgumentParser(description="灌入演示数据（幂等）")
    parser.add_argument("--check", action="store_true", help="只输出当前行数，不写库")
    args = parser.parse_args()

    async def runner() -> int:
        try:
            counts = await seed(check_only=args.check)
        finally:
            await dispose_engine()
        print("表行数：")
        for name, value in counts.items():
            print(f"  {name:<20} {value}")
        return 0

    raise SystemExit(asyncio.run(runner()))


if __name__ == "__main__":
    main()

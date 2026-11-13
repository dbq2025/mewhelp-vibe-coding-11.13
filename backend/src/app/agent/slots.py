"""槽位抽取与多轮指代解析（纯规则，不花 LLM 一次调用）。

设计取舍（计划 4.4）：订单号、手机尾号、价格区间、售后类型这几类槽位**有确定形态**，
用正则抽比让模型抽更准、更快、更便宜，而且可单测。LLM 只负责它擅长的部分
（意图判定、口语化关键词、需要推理的对比请求）。

指代解析优先级：本轮工具结果 > 槽位 product_id > 上轮候选列表序号。
"第二个多少钱" 这类追问必须走确定性解析——让模型猜序号，一次猜错就是一段编造的价格。
"""

from __future__ import annotations

import re
from typing import Any

# 订单号：种子数据形如 20261101001（20 开头 11 位），与手机号（1 开头）天然区分。
# 用「前后不是数字」而不是 \b：中文紧邻数字时 \b 不成立（"订单号20261101001已发货"匹配不到）
_ORDER_NO = re.compile(r"(?<!\d)(20\d{9})(?!\d)")
# 手机号（用于从"手机尾号 0002"里取后四位，也用于输出后置校验）
_PHONE = re.compile(r"(?<!\d)(1[3-9]\d{9})(?!\d)")
_PHONE_TAIL = re.compile(r"(?:手机)?尾号\s*(?:是|为|:)?\s*(\d{4})\b")

_PRICE_MAX = [
    re.compile(r"(\d+(?:\.\d+)?)\s*(?:元|块|rmb|¥)?\s*(?:以内|以下|之内|左右|封顶|内)"),
    re.compile(r"不超过\s*(\d+(?:\.\d+)?)"),
    re.compile(r"预算\s*(\d+(?:\.\d+)?)"),
    re.compile(r"(\d+(?:\.\d+)?)\s*(?:元|块)?\s*以下的"),
]
_PRICE_MIN = [re.compile(r"(\d+(?:\.\d+)?)\s*(?:元|块)?\s*以上")]
_PRICE_RANGE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:元|块)?\s*(?:到|至|-|~)\s*(\d+(?:\.\d+)?)")

# 指代序号：第一个 / 第二个 / 第 2 个 / 最后那个
_ORDINAL = re.compile(r"第\s*([一二三四五六七八九十\d])\s*(?:个|款|件|台|只|条)?")
_LAST = re.compile(r"(?:最后|最末)\s*(?:一)?\s*(?:个|款|件|台|只|条)")
_THIS_ONE = re.compile(r"(?:这个|这款|那个|那款|它|这一款|那一款)")

_DIGITS = {
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}

_AFTER_SALES_TYPES = {
    "退货": "return",
    "退款": "refund",
    "换货": "exchange",
    "换一个": "exchange",
    "维修": "repair",
    "保修": "repair",
}

# 这些槽位变化时前端要提示"已识别…"
SURFACE_SLOTS = (
    "order_no",
    "phone_tail",
    "price_max",
    "price_min",
    "product_id",
    "after_sales_type",
)


def _yuan_to_cents(text: str) -> int:
    return round(float(text) * 100)


def extract_rules(text: str, slots: dict[str, Any]) -> dict[str, Any]:
    """从一句话里抽确定性槽位。只返回抽到的键，没抽到的不覆盖已有值。"""
    found: dict[str, Any] = {}
    raw = text or ""

    order_match = _ORDER_NO.search(raw)
    if order_match:
        found["order_no"] = order_match.group(1)

    tail_match = _PHONE_TAIL.search(raw)
    if tail_match:
        found["phone_tail"] = tail_match.group(1)
    else:
        phone_match = _PHONE.search(raw)
        if phone_match:
            found["phone_tail"] = phone_match.group(1)[-4:]

    range_match = _PRICE_RANGE.search(raw)
    if range_match:
        found["price_min"] = _yuan_to_cents(range_match.group(1))
        found["price_max"] = _yuan_to_cents(range_match.group(2))
    else:
        for pattern in _PRICE_MAX:
            match = pattern.search(raw)
            if match:
                found["price_max"] = _yuan_to_cents(match.group(1))
                break
        for pattern in _PRICE_MIN:
            match = pattern.search(raw)
            if match:
                found["price_min"] = _yuan_to_cents(match.group(1))
                break

    for word, kind in _AFTER_SALES_TYPES.items():
        if word in raw:
            found["after_sales_type"] = kind
            break

    referenced = resolve_reference(raw, slots)
    if referenced is not None:
        found["product_id"] = referenced

    return found


def ordinal_of(text: str) -> int | None:
    """返回 1 起的序号；不是序号表达则 None。"""
    match = _ORDINAL.search(text or "")
    if match:
        token = match.group(1)
        if token.isdigit():
            return int(token)
        return _DIGITS.get(token)
    if _LAST.search(text or ""):
        return -1  # 负数代表"最后一个"，由调用方结合候选长度换算
    return None


def resolve_reference(text: str, slots: dict[str, Any]) -> int | None:
    """把"第二个/这个/它"解析成 product_id。解析不出来就返回 None，绝不猜。

    候选不足时同样返回 None：宁可追问"你指哪一款"，也不要报错价。
    """
    candidates = slots.get("last_products") or []
    if not isinstance(candidates, list) or not candidates:
        return None

    index = ordinal_of(text)
    if index is not None:
        if index == -1:
            index = len(candidates)
        if 1 <= index <= len(candidates):
            item = candidates[index - 1]
            if isinstance(item, dict) and item.get("id") is not None:
                return int(item["id"])
        return None

    if _THIS_ONE.search(text or "") and len(candidates) == 1:
        item = candidates[0]
        if isinstance(item, dict) and item.get("id") is not None:
            return int(item["id"])
    return None


def merge_slots(
    current: dict[str, Any], incoming: dict[str, Any]
) -> tuple[dict[str, Any], list[str]]:
    """合并槽位，返回 (新槽位, 变化的键)。

    空值不覆盖：模型这轮没提到的槽位，要保留上一轮的值（否则"它多少钱"就丢了商品）。
    订单号变化算冲突，交由调用方清空与旧订单绑定的字段。
    """
    merged = dict(current or {})
    changed: list[str] = []
    for key, value in (incoming or {}).items():
        if value is None or value == "" or value == []:
            continue
        if merged.get(key) != value:
            merged[key] = value
            changed.append(key)
    return merged, changed


def summarize_changes(changed: list[str], slots: dict[str, Any]) -> dict[str, Any]:
    """给 SSE `slots` 事件用的可读摘要（前端只展示，不参与逻辑）。"""
    labels = {
        "order_no": "订单号",
        "phone_tail": "手机尾号",
        "price_max": "价格上限",
        "price_min": "价格下限",
        "product_id": "商品",
        "after_sales_type": "售后类型",
    }
    payload: dict[str, Any] = {}
    for key in changed:
        if key not in SURFACE_SLOTS:
            continue
        value = slots.get(key)
        if key in ("price_max", "price_min") and isinstance(value, int):
            payload[key] = f"¥{value / 100:.0f}"
        else:
            payload[key] = value
    return {"changed": [labels.get(k, k) for k in changed if k in SURFACE_SLOTS], "values": payload}


def mask_order_no(order_no: str) -> str:
    """日志与提示里只留首尾，避免订单号在日志中裸露。"""
    if len(order_no) <= 6:
        return order_no
    return f"{order_no[:4]}***{order_no[-3:]}"

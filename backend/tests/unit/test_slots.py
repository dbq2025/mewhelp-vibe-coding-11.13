"""槽位抽取与指代解析的单测（纯函数，无 IO）。"""

from __future__ import annotations

from app.agent import slots as slot_utils


def test_extract_order_no_and_phone_tail() -> None:
    found = slot_utils.extract_rules("订单 20261101001 的手机尾号是 0002，帮我查下", {})
    assert found["order_no"] == "20261101001"
    assert found["phone_tail"] == "0002"


def test_extract_price_max_converts_yuan_to_cents() -> None:
    assert slot_utils.extract_rules("1000 以内的降噪耳机", {})["price_max"] == 100000
    assert slot_utils.extract_rules("预算 500 元", {})["price_max"] == 50000


def test_extract_price_range() -> None:
    found = slot_utils.extract_rules("500 到 800 元之间的耳机", {})
    assert found["price_min"] == 50000
    assert found["price_max"] == 80000


def test_extract_after_sales_type() -> None:
    assert slot_utils.extract_rules("这个我想退货", {})["after_sales_type"] == "return"
    assert slot_utils.extract_rules("能换个颜色吗，换货", {})["after_sales_type"] == "exchange"


def test_ordinal_resolves_second_candidate() -> None:
    slots = {
        "last_products": [
            {"id": 11, "name": "A"},
            {"id": 22, "name": "B"},
            {"id": 33, "name": "C"},
        ]
    }
    assert slot_utils.resolve_reference("第二个多少钱", slots) == 22
    assert slot_utils.resolve_reference("第 3 款呢", slots) == 33
    assert slot_utils.resolve_reference("最后一个有货吗", slots) == 33


def test_ordinal_out_of_range_returns_none() -> None:
    slots = {"last_products": [{"id": 11, "name": "A"}]}
    # 越界不猜：让 Agent 追问，而不是报错价
    assert slot_utils.resolve_reference("第五个多少钱", slots) is None


def test_pronoun_without_candidates_returns_none() -> None:
    assert slot_utils.resolve_reference("这个多少钱", {}) is None


def test_merge_slots_keeps_previous_when_incoming_empty() -> None:
    merged, changed = slot_utils.merge_slots(
        {"keyword": "耳机", "price_max": 100000}, {"keyword": None}
    )
    assert merged["keyword"] == "耳机"
    assert changed == []


def test_merge_slots_reports_changed_keys() -> None:
    merged, changed = slot_utils.merge_slots({"keyword": "耳机"}, {"keyword": "充电宝"})
    assert merged["keyword"] == "充电宝"
    assert changed == ["keyword"]


def test_summarize_changes_formats_price() -> None:
    payload = slot_utils.summarize_changes(["price_max", "_low_conf"], {"price_max": 100000})
    assert payload["changed"] == ["价格上限"]
    assert payload["values"]["price_max"] == "¥1000"

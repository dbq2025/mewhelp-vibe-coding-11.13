"""售后受理的纯逻辑单测：可受理判定、类型归一、质量问题识别。

这些规则一旦写错，后果是"该拒的没拒"（超期退货被受理）或"该受的拒了"（质量问题被卡）。
所以全部写成纯函数，不查库、不调模型。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.domain.services.after_sales import (
    NO_REASON_DAYS,
    check_eligibility,
    is_quality_issue,
    normalize_type,
)
from app.infra.db.models.order import Order


def _order(status: str, *, days_ago: int = 1) -> Order:
    """构造一个不入库的 Order 实例：可受理判定是纯函数，不需要 session。"""
    paid = datetime.now(UTC) - timedelta(days=days_ago)
    return Order(
        order_no="20261101008",
        user_id=1,
        status=status,
        total_cents=15900,
        receiver_phone_tail="0001",
        paid_at=paid,
        created_at=paid,
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("return", "return"),
        ("refund", "return"),
        ("退货", "return"),
        ("exchange", "exchange"),
        ("换货", "exchange"),
        ("repair", "repair"),
        ("保修", "repair"),
        ("", None),
        ("随便看看", None),
    ],
)
def test_normalize_type(raw: str, expected: str | None) -> None:
    assert normalize_type(raw) == expected


def test_quality_words_detected() -> None:
    assert is_quality_issue("耳机有杂音，左边不响")
    assert is_quality_issue("收到就是破损的")
    assert not is_quality_issue("就是不想要了")


def test_pending_pay_rejected() -> None:
    verdict = check_eligibility(_order("pending_pay"), "return")
    assert not verdict.ok
    assert "还没付款" in verdict.hint


def test_pending_ship_redirects_to_cancel() -> None:
    """未发货不收售后单：直接取消订单更快，否则会污染售后工单统计。"""
    verdict = check_eligibility(_order("pending_ship"), "return")
    assert not verdict.ok
    assert verdict.redirect == "cancel_order"


def test_closed_and_refunding_rejected() -> None:
    assert not check_eligibility(_order("closed"), "return").ok
    refunding = check_eligibility(_order("refunding"), "return")
    assert not refunding.ok
    assert "退款流程" in refunding.hint


def test_shipped_and_delivered_accepted() -> None:
    assert check_eligibility(_order("shipped"), "return").ok
    assert check_eligibility(_order("delivered"), "exchange").ok
    assert check_eligibility(_order("delivered"), "repair").ok


def test_return_over_seven_days_rejected_without_quality_reason() -> None:
    verdict = check_eligibility(_order("delivered", days_ago=NO_REASON_DAYS + 2), "return")
    assert not verdict.ok
    assert "无理由" in verdict.hint


def test_return_over_seven_days_allowed_for_quality_issue() -> None:
    verdict = check_eligibility(
        _order("delivered", days_ago=NO_REASON_DAYS + 2),
        "return",
        "用了两周发现充不进电，电池有问题",
    )
    assert verdict.ok


def test_unknown_type_rejected() -> None:
    verdict = check_eligibility(_order("delivered"), "unknown")
    assert not verdict.ok

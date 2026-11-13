"""二次确认词识别单测。

这是写操作的最后一道闸：判错一次就是一张真实工单。
核心断言是"短句认、长句不认、否定优先"。
"""

from __future__ import annotations

import pytest

from app.agent.slots import classify_confirmation


@pytest.mark.parametrize(
    "text",
    ["确认提交", "确认", "是的", "对", "好的", "可以", "没问题", "嗯嗯", "就这样", "提交吧"],
)
def test_short_confirmation_recognized(text: str) -> None:
    assert classify_confirmation(text) == "confirm"


@pytest.mark.parametrize(
    "text",
    ["取消", "算了", "不要了", "先不申请", "不用了谢谢", "不行", "再想想", "暂时不要"],
)
def test_denial_recognized(text: str) -> None:
    assert classify_confirmation(text) == "deny"


@pytest.mark.parametrize(
    "text",
    [
        "对了我还想问下运费怎么算",
        "好的，那这款耳机有货吗，另外一个颜色呢",
        "我要退货",
        "",
        "？？",
    ],
)
def test_long_or_unrelated_not_treated_as_confirmation(text: str) -> None:
    """长句里通常还有别的事，当确认处理会误建单。"""
    assert classify_confirmation(text) is None


def test_denial_wins_over_confirmation_words() -> None:
    """'不用了谢谢' 含 '好的/好' 的同义字，必须判否定。"""
    assert classify_confirmation("不用了谢谢") == "deny"
    assert classify_confirmation("不要了谢谢") == "deny"

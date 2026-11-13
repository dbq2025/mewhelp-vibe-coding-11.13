"""输入守卫与输出后置校验。

两条铁律（agent.md §12）：
1. **输入侧**：超长、注入尝试、明显刷屏直接拦截，不把可疑内容送进 prompt；
2. **输出侧**：模型说的话不能自带"未被授权的事实"——出现别人的订单号、完整手机号一律改写。
   校验不通过时不是"再让模型改一遍"（它会换个说法继续编），而是替换成模板回答。
"""

from __future__ import annotations

import re
import time
from collections import deque
from dataclasses import dataclass

from app.agent.slots import _ORDER_NO, _PHONE
from app.core.config import get_settings

# 注入模式：中英文常见越权指令。命中即拦截，不做"善意解读"。
_INJECTION_PATTERNS = [
    re.compile(r"忽略(以上|之前|上面|前面)?.{0,6}(指令|提示|设定|规则)"),
    re.compile(r"(ignore|disregard)\s+(all\s+)?(previous|prior|above)\s+(instruction|prompt)"),
    re.compile(r"(system|developer)\s*prompt", re.IGNORECASE),
    re.compile(r"你现在(是|扮演)"),
    re.compile(r"打印.{0,4}(你的)?(系统|system)"),
    re.compile(r"重复(你|你的)?.{0,4}(设定|规则|提示词)"),
    re.compile(r"<\|.{0,20}\|>"),
]

# 明显刷屏：单字符重复 30 次以上
_SPAM = re.compile(r"(.)\1{29,}")

BLOCK_MESSAGE = "这个问题我无法处理。如果你想咨询商品、订单或售后政策，可以直接告诉我具体情况。"
BLOCK_INJECTION_MESSAGE = (
    "我不能跳过规则来处理这类请求。如果你有商品、订单或售后的问题，我很乐意帮忙。"
)


@dataclass(frozen=True, slots=True)
class GuardResult:
    allowed: bool
    reason: str = ""
    message: str = ""


class RateLimiter:
    """进程内滑动窗口。单实例部署够用；多实例时应换成 Redis（计划 6.5）。

    键用 session_id 而不是 IP：本项目按会话计费，同一会话刷屏才是真实风险。
    """

    def __init__(self, limit: int, window_seconds: float = 60.0) -> None:
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = {}

    def hit(self, key: str) -> bool:
        """返回 True 表示放行。"""
        now = time.monotonic()
        bucket = self._hits.setdefault(key, deque())
        while bucket and now - bucket[0] > self.window:
            bucket.popleft()
        if len(bucket) >= self.limit:
            return False
        bucket.append(now)
        return True

    def reset(self, key: str) -> None:
        self._hits.pop(key, None)


_limiter = RateLimiter(get_settings().rate_limit_per_minute)


def check_input(text: str, *, session_id: str) -> GuardResult:
    settings = get_settings()
    stripped = (text or "").strip()

    if not stripped:
        return GuardResult(False, "empty", "请先描述一下你的问题。")

    if len(stripped) > settings.guard_max_input_chars:
        return GuardResult(
            False,
            "too_long",
            f"这条消息太长了（{len(stripped)} 字）。请把问题拆短一点，我一次能处理"
            f"{settings.guard_max_input_chars} 字以内。",
        )

    for pattern in _INJECTION_PATTERNS:
        if pattern.search(stripped):
            return GuardResult(False, "injection", BLOCK_INJECTION_MESSAGE)

    if _SPAM.search(stripped):
        return GuardResult(False, "spam", BLOCK_MESSAGE)

    if not _limiter.hit(session_id):
        return GuardResult(
            False,
            "rate_limited",
            f"提问有点频繁（每分钟最多 {settings.rate_limit_per_minute} 条），稍等一下再问。",
        )

    return GuardResult(True)


# ------------------------------------------------------------------ 输出校验
def scrub_output(text: str, *, allowed_order_nos: set[str]) -> tuple[str, list[str]]:
    """把草稿里不该出现的敏感事实改写掉，返回 (新文本, 命中原因列表)。

    - 别人的订单号：替换为「另一笔订单」，避免通过回答泄漏他人订单存在性；
    - 完整手机号：脱敏为 138****0001；
    - 本会话被授权访问的订单号保留（用户自己问的单可以回显）。
    """
    reasons: list[str] = []
    result = text or ""

    for match in _ORDER_NO.finditer(result):
        order_no = match.group(1)
        if order_no in allowed_order_nos:
            continue
        result = result.replace(order_no, "另一笔订单")
        reasons.append("foreign_order_no")

    def _mask(match: re.Match[str]) -> str:
        phone = match.group(1)
        reasons.append("full_phone")
        return f"{phone[:3]}****{phone[-4:]}"

    result = _PHONE.sub(_mask, result)
    return result, sorted(set(reasons))


def fallback_answer(reason: str) -> str:
    """LLM 不可用/输出不可信时的固定话术。宁可少说，不可编造。"""
    if reason == "llm_unavailable":
        return (
            "抱歉，我这边暂时联系不上应答服务，没法给你准确的答案。"
            "你可以稍后重试，或者需要的话我帮你转人工客服。"
        )
    return (
        "抱歉，这个问题我暂时没法给出可靠回答。你可以换个说法再问一次，或者我帮你转人工客服跟进。"
    )


# ------------------------------------------------------------------ 流式校验
HOLD_BACK_CHARS = 40


class StreamingScrubber:
    """边流边校验：hold-back 缓冲 + 数字边界对齐。

    为什么不能"先流完再校验"：内容已经送到浏览器了，改不了。
    这里的做法是每次只放行 `buffer[:-40]`，并且如果切点正好落在数字中间，
    就把切点往前挪到数字开头——保证任何 11 位订单号都完整落在某一段里，
    不会出现"前半段正常、后半段泄漏"的拼接。
    """

    def __init__(self, *, allowed_order_nos: set[str]) -> None:
        self.allowed = allowed_order_nos
        self.buffer = ""
        self.reasons: set[str] = set()
        self.dropped = False

    def feed(self, text: str) -> str:
        if self.dropped or not text:
            return ""
        self.buffer += text
        if len(self.buffer) <= HOLD_BACK_CHARS:
            return ""
        cut = len(self.buffer) - HOLD_BACK_CHARS
        while cut > 0 and self.buffer[cut].isdigit() and self.buffer[cut - 1].isdigit():
            cut -= 1
        segment, self.buffer = self.buffer[:cut], self.buffer[cut:]
        clean, reasons = scrub_output(segment, allowed_order_nos=self.allowed)
        self.reasons.update(reasons)
        return clean

    def flush(self) -> str:
        if self.dropped or not self.buffer:
            return ""
        segment, self.buffer = self.buffer, ""
        clean, reasons = scrub_output(segment, allowed_order_nos=self.allowed)
        self.reasons.update(reasons)
        return clean

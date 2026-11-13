"""输入守卫与输出后置校验。

两条铁律（agent.md §12）：
1. **输入侧**：超长、注入尝试、明显刷屏直接拦截，不把可疑内容送进 prompt；
2. **输出侧**：模型说的话不能自带"未被授权的事实"——出现别人的订单号、完整手机号一律改写。
   校验不通过时不是"再让模型改一遍"（它会换个说法继续编），而是替换成模板回答。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.agent.slots import _PHONE
from app.core.config import get_settings

# 会话级限流直接用 HTTP 层那个滑动窗口单例（键加 "session:" 前缀区分维度）
from app.core.ratelimit import limiter as session_limiter

# 注入模式：中英文常见越权指令。命中即拦截，不做"善意解读"。
_INJECTION_PATTERNS = [
    re.compile(r"忽略(以上|之前|上面|前面)?.{0,6}(指令|提示|设定|规则)"),
    re.compile(r"(ignore|disregard)\s+(all\s+)?(previous|prior|above)\s+(instruction|prompt)"),
    re.compile(r"(system|developer)\s*prompt", re.IGNORECASE),
    re.compile(r"你现在(是|扮演)"),
    re.compile(r"打印.{0,4}(你的)?(系统|system)"),
    re.compile(r"重复(你|你的)?.{0,4}(设定|规则|提示词)"),
    re.compile(r"<\|.{0,20}\|>"),
    # P4 对抗集补的两类：① 骗模型复述系统消息；② 骗模型承诺事实之外的补偿。
    # 这两个模式刻意写窄（必须同时出现"复述类动词 + 系统消息类名词"），
    # 否则"帮我复述一下退货规则"这种正常提问会被误拦。
    re.compile(
        r"(复述|重复|打印|输出|告诉我).{0,12}(系统消息|系统提示|提示词|你的设定|对话规则|初始设定)"
    ),
    re.compile(r"忽略.{0,6}(事实|规则|限制|校验|权限|指令)"),
    re.compile(r"(保证|承诺).{0,8}(全额赔付|免费送|免费领)"),
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


# 会话级限流复用 HTTP 层那个滑动窗口（`core.ratelimit.limiter`），只是换了个键前缀。
# 为什么不再单独实现一份：两套窗口迟早会出现"网关说没超、守卫说超了"的对不上账，
# 而且 0=关闭 的语义只需要在一个地方定义一次。
# 为什么会话维度还要限：IP 限流挡的是机器，会话限流挡的是"一个用户把预算烧光"。
_SESSION_KEY = "session:"


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

    allowed, _retry_after = session_limiter.hit(f"{_SESSION_KEY}{session_id}")
    if not allowed:
        return GuardResult(
            False,
            "rate_limited",
            f"提问有点频繁（每分钟最多 {settings.rate_limit_per_minute} 条），稍等一下再问。",
        )

    return GuardResult(True)


# ------------------------------------------------------------------ 输出校验
# 输出脱敏用：允许把紧邻的「订单」一起替换，避免出现「订单 另一笔订单」的病句
_PREFIXED_ORDER_NO = re.compile(r"(?:订单\s*)?(?<!\d)(20\d{9})(?!\d)")


def scrub_output(text: str, *, allowed_order_nos: set[str]) -> tuple[str, list[str]]:
    """把草稿里不该出现的敏感事实改写掉，返回 (新文本, 命中原因列表)。

    - 别人的订单号：替换为「另一笔订单」，避免通过回答泄漏他人订单存在性；
    - 完整手机号：脱敏为 138****0001；
    - 本会话被授权访问的订单号保留（用户自己问的单可以回显）。
    """
    reasons: list[str] = []
    result = text or ""

    def _mask_order(match: re.Match[str]) -> str:
        if match.group(1) in allowed_order_nos:
            return match.group(0)
        reasons.append("foreign_order_no")
        # 连前面紧跟的「订单」一起吃掉，否则会读成「查不到订单 另一笔订单 的物流」
        return "另一笔订单"

    result = _PREFIXED_ORDER_NO.sub(_mask_order, result)

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


# 流式切点的保护规则：不能落在「订」「单」「订单 」「订单+数字」中间
_BOUNDARY_SPLIT = re.compile(r"(?:订|单|订单\s*)\d*$")


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
        # 切点不能把「订」「单」「订单 」「订单 + 数字」切开：
        # 一旦前半段先吐出「订单 」，后半段的单号被替换后会拼成「订单 另一笔订单」。
        guard = _BOUNDARY_SPLIT.search(self.buffer[:cut])
        if guard is not None:
            cut = guard.start()
        if cut <= 0:
            return ""
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

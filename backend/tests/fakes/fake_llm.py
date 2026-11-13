"""测试用假 LLM。

铁律（agent.md §9）：测试里禁止打真实模型。所有图/接口测试都注入这里，
真实模型只出现在 `scripts/eval*.py`。

用法：
    fake = FakeLlm(plans=[{"intent": "product_search", ...}], answers=["第一段", "第二段"])
    set_llm_client(fake)
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence
from typing import Any

from app.agent.llm import LlmClient, Usage


class FakeLlm(LlmClient):
    """按队列回放预设响应；队列空了用默认值兜底，保证测试不会因少一条配置而挂。"""

    def __init__(
        self,
        *,
        plans: list[dict[str, Any]] | None = None,
        answers: list[str] | None = None,
        delay: float = 0.0,
        fail_stream: bool = False,
    ) -> None:
        super().__init__(api_key="fake-key")
        self.plans = list(plans or [])
        self.answers = list(answers or [])
        self.delay = delay
        self.fail_stream = fail_stream
        self.calls: list[list[dict[str, str]]] = []

    def configured(self) -> bool:
        return True

    async def complete_json(
        self,
        messages: Sequence[dict[str, str]],
        *,
        max_tokens: int | None = None,
        usage: Usage | None = None,
    ) -> tuple[dict[str, Any], Usage]:
        self.calls.append(list(messages))
        plan = self.plans.pop(0) if self.plans else {"intent": "chitchat", "confidence": 0.9}
        result_usage = Usage(prompt_tokens=100, completion_tokens=20)
        if usage is not None:
            usage.merge(result_usage)
        return plan, result_usage

    async def stream_text(
        self,
        messages: Sequence[dict[str, str]],
        *,
        usage: Usage | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> AsyncIterator[str]:
        self.calls.append(list(messages))
        if self.fail_stream:
            raise RuntimeError("fake llm down")
        answer = self.answers.pop(0) if self.answers else "好的，我帮你确认一下。"
        if self.delay:
            import asyncio

            await asyncio.sleep(self.delay)
        for index in range(0, len(answer), 4):
            yield answer[index : index + 4]
        if usage is not None:
            usage.prompt_tokens = 300
            usage.completion_tokens = len(answer)


def plan(**kwargs: Any) -> dict[str, Any]:
    """便捷构造：plan(intent="product_search", confidence=0.9, slots={...})"""
    base: dict[str, Any] = {
        "intent": "chitchat",
        "confidence": 0.9,
        "slots": {},
        "need_clarify": False,
        "clarify_question": None,
        "tool_plan": [],
    }
    base.update(kwargs)
    return base


def sse_events(raw: str) -> list[tuple[str, dict[str, Any]]]:
    """把 SSE 原始文本解析成 [(event, data)]，测试断言事件序列用。"""
    events: list[tuple[str, dict[str, Any]]] = []
    for block in raw.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        name = ""
        data = ""
        for line in block.splitlines():
            if line.startswith("event:"):
                name = line[6:].strip()
            elif line.startswith("data:"):
                data = line[5:].strip()
        if name:
            events.append((name, json.loads(data) if data else {}))
    return events

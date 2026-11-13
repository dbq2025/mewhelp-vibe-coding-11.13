"""LLM 客户端：OpenAI 兼容协议（DeepSeek / 百炼 / 任意兼容网关都能换）。

为什么自己写而不是引 SDK：只需要两个能力（流式补全 + JSON 输出），
而 OpenAI SDK 会把「重试策略、超时、错误码映射」藏在自己的抽象里。
本项目对这三件事有明确口径（计划 4.7），显式写出来更可控，也少一个重依赖。

错误口径：
- 超时 → 3001
- 429 → 3002
- 其它上游错误 → 5000（固定兜底话术，前端可重试）
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field

import httpx

from app.core.config import get_settings
from app.core.errors import CODE_LLM_TIMEOUT, CODE_UPSTREAM_RATE_LIMIT, AppError
from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class Usage:
    """token 计量。流式场景下由最后一块 chunk 回填，调用方传同一个对象进来。"""

    prompt_tokens: int = 0
    completion_tokens: int = 0

    def merge(self, other: Usage) -> None:
        self.prompt_tokens = other.prompt_tokens or self.prompt_tokens
        self.completion_tokens = other.completion_tokens or self.completion_tokens


@dataclass
class _Delta:
    text: str = ""
    usage: Usage | None = None
    done: bool = False


class LlmNotConfiguredError(AppError):
    def __init__(self) -> None:
        super().__init__(5000, "未配置 LLM_API_KEY，无法生成回答", 503)


@dataclass
class LlmClient:
    base_url: str = field(default_factory=lambda: get_settings().llm_base_url)
    api_key: str = field(default_factory=lambda: get_settings().llm_api_key)
    model: str = field(default_factory=lambda: get_settings().llm_model)
    timeout: float = field(default_factory=lambda: get_settings().llm_timeout_seconds)
    max_retries: int = field(default_factory=lambda: get_settings().llm_max_retries)

    def configured(self) -> bool:
        return bool(self.api_key)

    # ------------------------------------------------------------------ 内部
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _payload(
        self,
        messages: Sequence[dict[str, str]],
        *,
        max_tokens: int,
        temperature: float,
        stream: bool,
        json_mode: bool,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "model": self.model,
            "messages": list(messages),
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        if stream:
            # 只在流式时要求回传用量，兼容网关对非流式已默认返回
            payload["stream_options"] = {"include_usage": True}
        return payload

    @staticmethod
    def _map_http_error(status: int, body: str) -> AppError:
        snippet = body[:200].replace("\n", " ")
        if status == 429:
            return AppError(CODE_UPSTREAM_RATE_LIMIT, "模型服务繁忙，请稍后重试", 429)
        if status in (401, 403):
            return AppError(5000, "模型服务鉴权失败，请检查 LLM_API_KEY", 502)
        logger.warning("llm_http_error", status=status, body=snippet)
        return AppError(5000, "模型服务异常，请稍后重试", 502)

    async def _backoff(self, attempt: int) -> None:
        await asyncio.sleep(0.5 * (3**attempt))

    # ------------------------------------------------------------------ JSON
    async def complete_json(
        self,
        messages: Sequence[dict[str, str]],
        *,
        max_tokens: int | None = None,
        usage: Usage | None = None,
    ) -> tuple[dict[str, object], Usage]:
        """要求模型输出 JSON 对象，返回 (dict, usage)。

        不依赖 function calling：理解和生成用同一套 `response_format=json_object`，
        少一层工具协议，也便于用 Fake 客户端做确定性测试。
        """
        settings = get_settings()
        if not self.configured():
            raise LlmNotConfiguredError()

        payload = self._payload(
            messages,
            max_tokens=max_tokens or settings.understand_max_tokens,
            temperature=0.0,
            stream=False,
            json_mode=True,
        )
        last_error: AppError | None = None
        for attempt in range(self.max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.post(
                        f"{self.base_url.rstrip('/')}/chat/completions",
                        headers=self._headers(),
                        json=payload,
                    )
                if response.status_code >= 400:
                    raise self._map_http_error(response.status_code, response.text)
                data = response.json()
                content = data["choices"][0]["message"]["content"]
                parsed = _loads_json_object(content)
                result_usage = Usage(
                    prompt_tokens=int(data.get("usage", {}).get("prompt_tokens", 0) or 0),
                    completion_tokens=int(data.get("usage", {}).get("completion_tokens", 0) or 0),
                )
                if usage is not None:
                    usage.merge(result_usage)
                return parsed, result_usage
            except httpx.TimeoutException as exc:
                last_error = AppError(CODE_LLM_TIMEOUT, "模型响应超时，已自动重试", 504)
                logger.warning("llm_timeout", attempt=attempt, error=repr(exc))
            except httpx.HTTPError as exc:
                last_error = AppError(5000, "模型服务连接失败", 502)
                logger.warning("llm_transport_error", attempt=attempt, error=repr(exc))
            except (KeyError, ValueError, TypeError) as exc:
                # 模型返回了非法 JSON：重试一次通常就好了，不重试会把一次抖动放大成用户可见错误
                last_error = AppError(5000, "模型输出格式异常", 502)
                logger.warning("llm_bad_json", attempt=attempt, error=repr(exc))
            if attempt < self.max_retries:
                await self._backoff(attempt)
        raise last_error or AppError(5000, "模型服务异常", 502)

    # ------------------------------------------------------------------ 流式
    async def stream_text(
        self,
        messages: Sequence[dict[str, str]],
        *,
        usage: Usage | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> AsyncIterator[str]:
        """流式生成文本。**已经吐出首块后不再重试**，否则用户会看到重复内容。"""
        settings = get_settings()
        if not self.configured():
            raise LlmNotConfiguredError()

        payload = self._payload(
            messages,
            max_tokens=max_tokens or settings.llm_max_tokens,
            temperature=settings.llm_temperature if temperature is None else temperature,
            stream=True,
            json_mode=False,
        )

        emitted = False
        last_error: AppError | None = None
        for attempt in range(self.max_retries + 1):
            try:
                async for delta in self._stream_once(payload):
                    if delta.usage is not None and usage is not None:
                        usage.merge(delta.usage)
                    if delta.text:
                        emitted = True
                        yield delta.text
                    if delta.done:
                        return
                return
            except AppError as exc:
                last_error = exc
                if emitted:
                    # 已经流出去的内容收不回来，交给上层按"不完整"落库
                    raise
            except httpx.TimeoutException as exc:
                last_error = AppError(CODE_LLM_TIMEOUT, "模型响应超时", 504)
                logger.warning("llm_stream_timeout", attempt=attempt, error=repr(exc))
                if emitted:
                    raise last_error from exc
            except httpx.HTTPError as exc:
                last_error = AppError(5000, "模型服务连接中断", 502)
                logger.warning("llm_stream_transport", attempt=attempt, error=repr(exc))
                if emitted:
                    raise last_error from exc
            if attempt < self.max_retries:
                await self._backoff(attempt)
        raise last_error or AppError(5000, "模型服务异常", 502)

    async def _stream_once(self, payload: dict[str, object]) -> AsyncIterator[_Delta]:
        async with (
            httpx.AsyncClient(timeout=self.timeout) as client,
            client.stream(
                "POST",
                f"{self.base_url.rstrip('/')}/chat/completions",
                headers=self._headers(),
                json=payload,
            ) as response,
        ):
            if response.status_code >= 400:
                body = (await response.aread()).decode("utf-8", "ignore")
                raise self._map_http_error(response.status_code, body)

            async for line in response.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                raw = line[5:].strip()
                if raw == "[DONE]":
                    yield _Delta(done=True)
                    return
                try:
                    chunk = json.loads(raw)
                except json.JSONDecodeError:
                    # 个别网关会插入心跳/注释行，跳过即可，不中断整条流
                    continue
                usage_obj = chunk.get("usage")
                parsed_usage = None
                if usage_obj:
                    parsed_usage = Usage(
                        prompt_tokens=int(usage_obj.get("prompt_tokens", 0) or 0),
                        completion_tokens=int(usage_obj.get("completion_tokens", 0) or 0),
                    )
                choices = chunk.get("choices") or []
                text = ""
                if choices:
                    delta = choices[0].get("delta") or {}
                    text = str(delta.get("content") or "")
                    if choices[0].get("finish_reason"):
                        yield _Delta(text=text, usage=parsed_usage, done=True)
                        return
                if text or parsed_usage is not None:
                    yield _Delta(text=text, usage=parsed_usage)


def _loads_json_object(content: str) -> dict[str, object]:
    """容错解析：模型偶尔会包 ```` ```json ````，或前后带解释文字。"""
    text = (content or "").strip()
    if text.startswith("```"):
        text = text.split("```")[1] if len(text.split("```")) > 1 else text
        text = text.removeprefix("json").strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("模型未返回 JSON 对象") from None
        parsed = json.loads(text[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("模型返回的 JSON 不是对象")
    return parsed


_client: LlmClient | None = None


def get_llm_client() -> LlmClient:
    global _client
    if _client is None:
        _client = LlmClient()
    return _client


def set_llm_client(client: LlmClient | None) -> None:
    """测试注入点：测试里换成 Fake，禁止打真实模型（agent.md §9）。"""
    global _client
    _client = client

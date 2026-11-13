"""Embedding 客户端（OpenAI 兼容 `/embeddings`，默认硅基流动 bge-m3）。

三件事必须自己做，不能指望 SDK：
1. **批量 + 限并发**：一次 16 条、并发 4，既跑满带宽也不至于把免费额度打挂；
2. **可重试**：429/5xx/网络错误退避重试，4xx（除 429）直接失败——key 错不该重试 3 次；
3. **维度校验**：返回维度与配置不一致立刻报错。宁可灌库失败，也不能让 1024 维的列
   悄悄塞进别的向量长度，等检索时才炸。
"""

from __future__ import annotations

import asyncio

import httpx

from app.core.config import get_settings
from app.core.errors import CODE_LLM_TIMEOUT, CODE_UPSTREAM_RATE_LIMIT, AppError
from app.core.logging import get_logger

logger = get_logger(__name__)

_RETRYABLE_STATUS = {408, 409, 429, 500, 502, 503, 504}


class EmbeddingError(AppError):
    """Embedding 调用失败。消息面向开发者，不含 key 与请求体。"""

    def __init__(self, message: str, *, code: int = CODE_LLM_TIMEOUT) -> None:
        super().__init__(code=code, message=message, http_status=503)


class EmbeddingClient:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        dim: int | None = None,
        batch_size: int | None = None,
        concurrency: int | None = None,
        max_retries: int | None = None,
    ) -> None:
        settings = get_settings()
        self.base_url = (base_url or settings.embedding_base_url).rstrip("/")
        self.api_key = api_key if api_key is not None else settings.embedding_api_key
        self.model = model or settings.embedding_model
        self.dim = dim or settings.embedding_dim
        self.batch_size = batch_size or settings.embedding_batch_size
        self.concurrency = concurrency or settings.embedding_concurrency
        self.max_retries = (
            max_retries if max_retries is not None else settings.embedding_max_retries
        )
        self.timeout = settings.embedding_timeout_seconds

    def _ensure_key(self) -> None:
        if not self.api_key:
            raise EmbeddingError(
                "未配置 EMBEDDING_API_KEY，无法向量化。请在项目根目录 .env 填入后重试。"
            )

    async def _post_batch(self, client: httpx.AsyncClient, batch: list[str]) -> list[list[float]]:
        payload = {"model": self.model, "input": batch, "encoding_format": "float"}
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

        last_error: str = ""
        for attempt in range(1, self.max_retries + 1):
            try:
                response = await client.post(
                    f"{self.base_url}/embeddings", json=payload, headers=headers
                )
            except httpx.TimeoutException:
                last_error = "请求超时"
            except httpx.HTTPError as exc:
                last_error = f"网络错误：{type(exc).__name__}"
            else:
                if response.status_code == 200:
                    data = response.json()
                    vectors = [item["embedding"] for item in data["data"]]
                    self._validate(vectors, expected=len(batch))
                    return vectors
                if response.status_code in _RETRYABLE_STATUS:
                    last_error = f"上游返回 {response.status_code}"
                else:
                    # 401/403/404/422 这类重试没有意义，直接暴露
                    detail = response.text[:200]
                    code = (
                        CODE_UPSTREAM_RATE_LIMIT
                        if response.status_code == 429
                        else CODE_LLM_TIMEOUT
                    )
                    raise EmbeddingError(
                        f"Embedding 调用失败（HTTP {response.status_code}）：{detail}", code=code
                    )

            if attempt < self.max_retries:
                backoff = 0.8 * (2 ** (attempt - 1))
                logger.warning(
                    "embedding_retry", attempt=attempt, error=last_error, backoff=round(backoff, 2)
                )
                await asyncio.sleep(backoff)

        raise EmbeddingError(f"Embedding 重试 {self.max_retries} 次仍失败：{last_error}")

    def _validate(self, vectors: list[list[float]], *, expected: int) -> None:
        if len(vectors) != expected:
            raise EmbeddingError(f"Embedding 返回条数不符：期望 {expected}，实际 {len(vectors)}")
        for vector in vectors:
            if len(vector) != self.dim:
                raise EmbeddingError(
                    f"Embedding 维度不符：期望 {self.dim}，实际 {len(vector)}。"
                    "请确认 EMBEDDING_MODEL 与 EMBEDDING_DIM 是否匹配。"
                )

    async def embed_documents(
        self, texts: list[str], *, progress_every: int = 0
    ) -> list[list[float]]:
        """批量向量化，结果顺序与入参严格一致。"""
        self._ensure_key()
        if not texts:
            return []

        batches = [texts[i : i + self.batch_size] for i in range(0, len(texts), self.batch_size)]
        semaphore = asyncio.Semaphore(self.concurrency)
        results: list[list[list[float]]] = [[] for _ in batches]

        async with httpx.AsyncClient(timeout=self.timeout) as client:

            async def run(index: int, batch: list[str]) -> None:
                async with semaphore:
                    results[index] = await self._post_batch(client, batch)
                    if progress_every and (index + 1) % progress_every == 0:
                        logger.info("embedding_progress", done=index + 1, total=len(batches))

            await asyncio.gather(*(run(i, b) for i, b in enumerate(batches)))

        return [vector for batch in results for vector in batch]

    async def embed_query(self, text: str) -> list[float]:
        vectors = await self.embed_documents([text])
        return vectors[0]


_default_client: EmbeddingClient | None = None


def get_embedding_client() -> EmbeddingClient:
    """进程级单例；连接由内部 AsyncClient 每次调用创建，避免跨事件循环复用。"""
    global _default_client
    if _default_client is None:
        _default_client = EmbeddingClient()
    return _default_client

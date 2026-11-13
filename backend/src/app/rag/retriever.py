"""知识库检索：P1 只做纯向量（HNSW + 余弦距离），P3 再叠 jieba/bigram 关键词召回与 rerank。

设计取舍：
- **距离阈值比 top-k 更重要**。知识库只有 100 多个 chunk，随便问一句都能凑出 top5，
  如果不设阈值，Agent 就会拿着不相关段落编引用。超过 `rag_max_distance` 一律丢弃，
  宁可回答"没查到政策依据"。
- 返回 `distance` 而不是"score"，避免前端和评测对"分数越高越好/越低越好"理解不一。
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.infra.db.models.kb import KbChunk, KbDoc
from app.rag.embedding import EmbeddingClient, get_embedding_client

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    chunk_id: int
    doc_id: int
    doc_title: str
    category: str
    seq: int
    content: str
    distance: float

    def to_citation(self, index: int) -> dict[str, object]:
        """转成 SSE `citation` 事件与 messages.citations 的通用结构（api.md §4）。"""
        snippet = self.content.strip().replace("\n", " ")
        return {
            "index": index,
            "docId": self.doc_id,
            "chunkId": self.chunk_id,
            "title": self.doc_title,
            "snippet": snippet[:200],
        }


def _base_stmt(vector: list[float]) -> Select[tuple[KbChunk, KbDoc, float]]:
    distance = KbChunk.embedding.cosine_distance(vector).label("distance")
    return (
        select(KbChunk, KbDoc, distance)
        .join(KbDoc, KbDoc.id == KbChunk.doc_id)
        .where(KbChunk.embedding.is_not(None))
        .order_by(distance)
    )


async def search(
    session: AsyncSession,
    query: str,
    *,
    top_k: int | None = None,
    max_distance: float | None = None,
    category: str | None = None,
    embedder: EmbeddingClient | None = None,
) -> list[RetrievedChunk]:
    """向量检索。query 为空返回空列表（不发起 embedding 调用，省一次计费）。"""
    query = (query or "").strip()
    if not query:
        return []

    settings = get_settings()
    top_k = top_k or settings.rag_top_k
    max_distance = settings.rag_max_distance if max_distance is None else max_distance

    client = embedder or get_embedding_client()
    vector = await client.embed_query(query)

    stmt = _base_stmt(vector).limit(max(top_k * 3, top_k))
    if category:
        stmt = stmt.where(KbDoc.category == category)

    rows = (await session.execute(stmt)).all()
    results = [
        RetrievedChunk(
            chunk_id=chunk.id,
            doc_id=doc.id,
            doc_title=doc.title,
            category=doc.category,
            seq=chunk.seq,
            content=chunk.content,
            distance=float(distance),
        )
        for chunk, doc, distance in rows
        if float(distance) <= max_distance
    ][:top_k]

    logger.info(
        "rag_search",
        query_len=len(query),
        candidates=len(rows),
        kept=len(results),
        max_distance=max_distance,
    )
    return results


async def search_as_citations(
    session: AsyncSession, query: str, *, top_k: int | None = None
) -> list[dict[str, object]]:
    chunks = await search(session, query, top_k=top_k)
    return [chunk.to_citation(i + 1) for i, chunk in enumerate(chunks)]

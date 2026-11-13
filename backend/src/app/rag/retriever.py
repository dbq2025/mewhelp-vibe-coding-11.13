"""知识库检索：向量（HNSW 余弦）+ 关键词（bigram tsvector）+ RRF 融合。

为什么要混合检索（计划 P3）：
纯向量对"专有说法"不敏感——用户问「运费谁出」「能不能开专票」时，向量可能召回
语义相近但结论相反的段落（运费规则里有"包邮"和"不包邮"两段）。关键词一路能把
字面完全命中的段落直接顶上来，两路用 RRF 融合比调权重更稳（不需要分数归一化）。

设计取舍：
- **距离阈值比 top-k 更重要**。知识库只有 100 多个 chunk，随便问一句都能凑出 top5，
  如果不设阈值，Agent 就会拿着不相关段落编引用。超过 `rag_max_distance` 一律丢弃。
  关键词命中的块同样要过这个阈值——否则"七天无理由"会命中"海外直邮不适用无理由"。
- **RRF 而不是加权分数**：向量距离越小越好、ts_rank 越大越好，量纲不同；
  RRF 只看排名，天然免疫量纲问题，也不用为"向量占几成"调参。
- 返回 `distance` 而不是"score"，避免前端和评测对"分数越高越好/越低越好"理解不一；
  `score` 只用于内部排序，不进 API。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.infra.db.models.kb import KbChunk, KbDoc
from app.rag.embedding import EmbeddingClient, get_embedding_client
from app.rag.segment import segment, to_tsquery

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
    # RRF 融合分（仅内部排序用，接口不返回）
    score: float = 0.0

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


@dataclass
class _Candidate:
    """融合过程中的中间态。用 dataclass 而不是 dict，避免 `object` 到处漏。"""

    chunk: KbChunk
    doc: KbDoc
    distance: float
    score: float


def _vector_stmt(vector: list[float], *, limit: int, category: str | None) -> Select[Any]:
    distance = KbChunk.embedding.cosine_distance(vector).label("distance")
    stmt = (
        select(KbChunk, KbDoc, distance)
        .join(KbDoc, KbDoc.id == KbChunk.doc_id)
        .where(KbChunk.embedding.is_not(None))
        .order_by(distance)
        .limit(limit)
    )
    if category:
        stmt = stmt.where(KbDoc.category == category)
    return stmt


def _keyword_stmt(
    vector: list[float], *, query: str, limit: int, category: str | None
) -> Select[Any] | None:
    """关键词召回：`to_tsvector('simple', content_seg) @@ to_tsquery(...)`。

    `content_seg` 是 bigram 预分词文本（见 `rag/segment.py`），所以不需要安装
    zhparser。tsquery 用 OR 连接，命中任意 bigram 即入候选，由 RRF 决定排序。
    顺带把余弦距离也算出来，让关键词命中的块也能过统一的距离阈值。
    """
    tsq_text = to_tsquery(query)
    if not tsq_text:
        return None
    tsv = func.to_tsvector("simple", KbChunk.content_seg)
    tsq = func.to_tsquery("simple", tsq_text)
    rank = func.ts_rank_cd(tsv, tsq).label("rank")
    distance = KbChunk.embedding.cosine_distance(vector).label("distance")
    stmt = (
        select(KbChunk, KbDoc, distance, rank)
        .join(KbDoc, KbDoc.id == KbChunk.doc_id)
        .where(KbChunk.embedding.is_not(None), tsv.op("@@")(tsq))
        .order_by(rank.desc())
        .limit(limit)
    )
    if category:
        stmt = stmt.where(KbDoc.category == category)
    return stmt


def _title_bonus(query: str, title: str, rrf_k: int) -> float:
    """标题命中的小幅加权：问"运费"时把《运费规则》顶到前面。

    上限约等于前进 1 个名次（1/(k+1)），不会盖过"内容更相关"的块。
    """
    query_tokens = set(segment(query).split())
    if not query_tokens:
        return 0.0
    title_tokens = set(segment(title).split())
    if not title_tokens:
        return 0.0
    ratio = len(query_tokens & title_tokens) / len(query_tokens)
    return ratio / (rrf_k + 1)


async def search(
    session: AsyncSession,
    query: str,
    *,
    top_k: int | None = None,
    max_distance: float | None = None,
    category: str | None = None,
    embedder: EmbeddingClient | None = None,
    mode: str | None = None,
) -> list[RetrievedChunk]:
    """检索。query 为空返回空列表（不发起 embedding 调用，省一次计费）。

    `mode`：`hybrid`（默认，向量 + 关键词 RRF）/ `vector`（纯向量，用于对照评测）。
    """
    query = (query or "").strip()
    if not query:
        return []

    settings = get_settings()
    top_k = top_k or settings.rag_top_k
    max_distance = settings.rag_max_distance if max_distance is None else max_distance
    mode = (mode or settings.rag_search_mode).lower()

    client = embedder or get_embedding_client()
    vector = await client.embed_query(query)

    candidates = max(top_k * 4, settings.rag_keyword_candidates)
    vec_rows = list(
        (await session.execute(_vector_stmt(vector, limit=candidates, category=category))).all()
    )

    fused: dict[int, _Candidate] = {}
    for rank, (chunk, doc, distance) in enumerate(vec_rows, start=1):
        fused[chunk.id] = _Candidate(
            chunk=chunk,
            doc=doc,
            distance=float(distance),
            score=1.0 / (settings.rag_rrf_k + rank),
        )

    keyword_hits = 0
    if mode == "hybrid":
        kw_stmt = _keyword_stmt(
            vector, query=query, limit=settings.rag_keyword_candidates, category=category
        )
        if kw_stmt is not None:
            try:
                kw_rows = list((await session.execute(kw_stmt)).all())
            except Exception as exc:
                # 关键词一路挂了不能拖垮整轮检索：向量结果还在，降级为纯向量
                logger.warning("rag_keyword_failed", error=repr(exc))
                kw_rows = []
            keyword_hits = len(kw_rows)
            for rank, (chunk, doc, distance, _rank) in enumerate(kw_rows, start=1):
                item = fused.setdefault(
                    chunk.id,
                    _Candidate(chunk=chunk, doc=doc, distance=float(distance), score=0.0),
                )
                item.score += 1.0 / (settings.rag_rrf_k + rank)

    results: list[RetrievedChunk] = []
    for item in fused.values():
        if item.distance > max_distance:
            continue
        results.append(
            RetrievedChunk(
                chunk_id=item.chunk.id,
                doc_id=item.doc.id,
                doc_title=item.doc.title,
                category=item.doc.category,
                seq=item.chunk.seq,
                content=item.chunk.content,
                distance=item.distance,
                score=item.score + _title_bonus(query, item.doc.title, settings.rag_rrf_k),
            )
        )

    results.sort(key=lambda row: row.score, reverse=True)
    results = results[:top_k]

    logger.info(
        "rag_search",
        query_len=len(query),
        mode=mode,
        vector_candidates=len(vec_rows),
        keyword_hits=keyword_hits,
        kept=len(results),
        max_distance=max_distance,
    )
    return results


async def search_as_citations(
    session: AsyncSession, query: str, *, top_k: int | None = None
) -> list[dict[str, object]]:
    chunks = await search(session, query, top_k=top_k)
    return [chunk.to_citation(i + 1) for i, chunk in enumerate(chunks)]

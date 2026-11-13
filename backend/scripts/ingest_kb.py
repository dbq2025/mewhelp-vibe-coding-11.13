"""知识库灌库：`data/kb/*.md` → 分块 → 向量化 → `kb_docs` / `kb_chunks`。

幂等策略：
- 文档按 `source`（文件名）定位，存在则更新 title/version，不存在则插入；
- 该文档的 chunk 整体重建（先删后插），保证重跑不会出现重复块；
- 语料里已删除的文件，其文档与块一并清理（打印数量，不静默删数据）。

用法：
    uv run python scripts/ingest_kb.py --dry-run   # 只分块，不调 API（不需要 key）
    uv run python scripts/ingest_kb.py             # 完整灌库（需要 EMBEDDING_API_KEY）
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sqlalchemy import delete, func, select

from app.core.config import get_settings
from app.infra.db.models.kb import KbChunk, KbDoc
from app.infra.db.session import SessionFactory, dispose_engine
from app.rag.chunking import chunk_markdown, doc_title_of, normalize
from app.rag.embedding import EmbeddingClient
from app.rag.segment import segment

KB_DIR = Path(__file__).resolve().parents[1] / "data" / "kb"

# 文档分类（决定 P3 检索时可选的 category 过滤）
_CATEGORY_BY_PREFIX: dict[str, str] = {
    "return": "售后政策",
    "seven-day": "售后政策",
    "exchange": "售后政策",
    "quality": "售后政策",
    "warranty": "售后政策",
    "shipping": "物流配送",
    "logistics": "物流配送",
    "delivery": "物流配送",
    "installation": "商品使用",
    "invoice": "支付发票",
    "payment": "支付发票",
    "price": "营销活动",
    "coupon": "营销活动",
    "membership": "营销活动",
    "order": "订单管理",
    "presale": "订单管理",
    "account": "账号安全",
    "password": "账号安全",
    "privacy": "隐私合规",
    "authenticity": "商品保障",
}


def _category_of(filename: str) -> str:
    for prefix, category in _CATEGORY_BY_PREFIX.items():
        if filename.startswith(prefix):
            return category
    return "其他"


def _load_corpus() -> list[dict[str, object]]:
    """读取全部 markdown，返回 [{source, title, category, chunks:[...]}]。"""
    settings = get_settings()
    docs: list[dict[str, object]] = []
    for path in sorted(KB_DIR.glob("*.md")):
        raw = normalize(path.read_text(encoding="utf-8"))
        if not raw:
            continue
        title = doc_title_of(raw) or path.stem
        chunks = chunk_markdown(
            raw,
            size=settings.rag_chunk_size,
            overlap=settings.rag_chunk_overlap,
        )
        docs.append(
            {
                "source": path.name,
                "title": title,
                "category": _category_of(path.stem),
                "chunks": chunks,
            }
        )
    return docs


async def ingest(*, dry_run: bool = False) -> dict[str, int]:
    docs = _load_corpus()
    total_chunks = sum(len(doc["chunks"]) for doc in docs)  # type: ignore[arg-type]
    stats = {"docs": len(docs), "chunks": total_chunks, "embedded": 0, "removed_docs": 0}

    print(f"扫描到 {len(docs)} 篇文档，切出 {total_chunks} 块")
    lengths = [len(chunk) for doc in docs for chunk in doc["chunks"]]  # type: ignore[union-attr]
    if lengths:
        print(f"块长度：min={min(lengths)} avg={sum(lengths) // len(lengths)} max={max(lengths)}")
    if dry_run:
        for doc in docs:
            print(f"  {doc['source']:<34} {len(doc['chunks']):>2} 块  {doc['title']}")  # type: ignore[arg-type]
        return stats

    client = EmbeddingClient()
    async with SessionFactory() as session:
        sources = [str(doc["source"]) for doc in docs]
        stale = (await session.scalars(select(KbDoc).where(KbDoc.source.not_in(sources)))).all()
        if stale:
            stale_ids = [doc.id for doc in stale]
            await session.execute(delete(KbChunk).where(KbChunk.doc_id.in_(stale_ids)))
            await session.execute(delete(KbDoc).where(KbDoc.id.in_(stale_ids)))
            stats["removed_docs"] = len(stale_ids)
            print(f"清理语料中已删除的文档 {len(stale_ids)} 篇")

        for doc in docs:
            source = str(doc["source"])
            existing = await session.scalar(select(KbDoc).where(KbDoc.source == source))
            if existing is None:
                kb_doc = KbDoc(
                    title=str(doc["title"]),
                    category=str(doc["category"]),
                    source=source,
                    version="v1",
                )
                session.add(kb_doc)
                await session.flush()
            else:
                kb_doc = existing
                kb_doc.title = str(doc["title"])
                kb_doc.category = str(doc["category"])
                kb_doc.version = "v1"

            chunks: list[str] = doc["chunks"]  # type: ignore[assignment]
            vectors = await client.embed_documents(chunks)
            stats["embedded"] += len(vectors)

            await session.execute(delete(KbChunk).where(KbChunk.doc_id == kb_doc.id))
            for seq, (content, vector) in enumerate(zip(chunks, vectors, strict=True)):
                session.add(
                    KbChunk(
                        doc_id=kb_doc.id,
                        seq=seq,
                        content=content,
                        content_seg=segment(content),
                        meta={"source": source, "title": kb_doc.title},
                        embedding=vector,
                    )
                )
            await session.commit()
            print(f"  {source:<34} {len(chunks):>2} 块 已入库")

        stats["docs_in_db"] = int(
            await session.scalar(select(func.count()).select_from(KbDoc)) or 0
        )
        stats["chunks_in_db"] = int(
            await session.scalar(select(func.count()).select_from(KbChunk)) or 0
        )
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="知识库灌库（幂等）")
    parser.add_argument("--dry-run", action="store_true", help="只分块统计，不调用 embedding")
    args = parser.parse_args()

    async def runner() -> int:
        try:
            stats = await ingest(dry_run=args.dry_run)
        finally:
            await dispose_engine()
        print("统计：" + ", ".join(f"{k}={v}" for k, v in stats.items()))
        return 0

    raise SystemExit(asyncio.run(runner()))


if __name__ == "__main__":
    main()

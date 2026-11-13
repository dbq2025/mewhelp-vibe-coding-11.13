"""知识库：政策原文 → 分块 → 向量。

中文全文检索不装 zhparser（Windows 编译坑），改用 jieba 预分词写入 content_seg，
再建 `to_tsvector('simple', content_seg)` 的 GIN 索引（计划 5.2）。
"""

from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, ForeignKey, Index, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.infra.db.base import Base

EMBEDDING_DIM = 1024


class KbDoc(Base):
    __tablename__ = "kb_docs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(50), index=True)
    source: Mapped[str] = mapped_column(String(200), default="")
    version: Mapped[str] = mapped_column(String(20), default="v1")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class KbChunk(Base):
    __tablename__ = "kb_chunks"
    __table_args__ = (
        Index(
            "uk_kb_chunks_doc_seq",
            "doc_id",
            "seq",
            unique=True,
        ),
        # 向量索引：余弦距离，HNSW 参数取经验值（m=16, ef_construction=64）
        Index(
            "idx_kb_chunks_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        # 关键词检索：content_seg 是 jieba 预分词后的空格分隔文本
        Index(
            "idx_kb_chunks_tsv",
            text("to_tsvector('simple', content_seg)"),
            postgresql_using="gin",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    doc_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("kb_docs.id", ondelete="CASCADE"), index=True
    )
    seq: Mapped[int] = mapped_column(default=0)
    content: Mapped[str] = mapped_column(Text)
    content_seg: Mapped[str] = mapped_column(Text, default="")
    meta: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default=text("'{}'::jsonb"))
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)

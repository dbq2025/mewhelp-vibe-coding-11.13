"""中文分词：字符二元组（bigram）。

为什么不是 jieba：
- 计划原本写 jieba 预分词写 `content_seg`，但 jieba 只发 sdist，构建过程会批量删除
  临时文件，在当前 Windows 开发环境下被安全策略拦下（`SAFE_DELETE_BULK_CONFIRM_REQUIRED`）；
- 本项目关键词检索只在 P3 作为混合检索的一路召回，且 `to_tsvector('simple', ...)` 不依赖
  词典，中文用 bigram 的召回率与"分词后按词匹配"基本同档，还省掉一份词典与内存。

约束：分词结果必须是空格分隔的 ASCII 安全文本，且**不含引号/反斜杠**，
否则拼 tsquery 时会被当成语法。这里只保留中文、字母、数字。
"""

from __future__ import annotations

import re

_NON_WORD = re.compile(r"[^\u4e00-\u9fffa-zA-Z0-9]+")
_CJK = re.compile(r"[\u4e00-\u9fff]")

_STOP_BIGRAMS = frozenset(
    {"我们", "你们", "可以", "这个", "那个", "什么", "怎么", "是否", "以及", "如果", "或者"}
)


def _segments(text: str) -> list[str]:
    """按非词字符切成片段，片段内中文走 bigram、英文数字整词保留。"""
    out: list[str] = []
    for piece in _NON_WORD.split(text):
        if not piece:
            continue
        if _CJK.search(piece):
            # 中文片段：单字保留 + 相邻二元组，单字保证"伞"这类短词也能命中
            out.extend(_CJK.findall(piece))
            out.extend(piece[i : i + 2] for i in range(len(piece) - 1))
            out.append(piece)  # 整段也留一份，长词直接命中优先级更高
        else:
            out.append(piece.lower())
    return out


def segment(text: str) -> str:
    """返回空格分隔的分词串，写入 `kb_chunks.content_seg`。"""
    if not text:
        return ""
    tokens: list[str] = []
    seen: set[str] = set()
    for token in _segments(text):
        token = token.strip().lower()
        if len(token) < 1 or token in seen or token in _STOP_BIGRAMS:
            continue
        seen.add(token)
        tokens.append(token)
    return " ".join(tokens)


def to_tsquery(query: str) -> str:
    """把查询串转成安全的 tsquery（OR 连接，取前 24 个词控制复杂度）。"""
    tokens = segment(query).split()[:24]
    return " | ".join(t.replace("'", "").replace("\\", "") for t in tokens if t)

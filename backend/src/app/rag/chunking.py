"""分块：按段落/句子边界切，带一点重叠。

为什么不用固定窗口硬切：政策文档里"七天无理由从签收起算"这类结论句一旦被切成
两半，向量会落在两个语义簇中间，检索得分反而低于无关段落。所以按句末标点收尾，
只在超长段落时退化为窗口切分。

参数口径（改这里要同步改 docs/eval.md 的评测记录）：
- chunk_size=360 字：bge-m3 对 300~500 字片段的检索表现较稳，且 6 个 chunk 能塞进 1 轮 context
- overlap=80 字：约 1~2 句，避免边界处信息丢失
- min_chunk=120 字：过短的尾块并入前一块
"""

from __future__ import annotations

import re

CHUNK_SIZE = 320
CHUNK_OVERLAP = 70
MIN_CHUNK = 100

_SENTENCE_END = re.compile(r"(?<=[。！？；\n])")
_MD_HEADING = re.compile(r"^(#{1,6})\s*(.+)$")


def normalize(text: str) -> str:
    """统一空白：保留段落（\\n\\n），压缩多余空格，去零宽字符。"""
    text = text.replace("\u200b", "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def split_sentences(paragraph: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_END.split(paragraph) if s.strip()]


def chunk_text(text: str, *, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """把整篇文档切成块。先按段落聚合到 size，再按句子兜底拆超长段落。"""
    text = normalize(text)
    if not text:
        return []

    units: list[str] = []
    for paragraph in text.split("\n\n"):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if len(paragraph) <= size:
            units.append(paragraph)
            continue
        # 超长段落：先按句子分组到 size 以内
        buffer = ""
        for sentence in split_sentences(paragraph):
            while len(sentence) > size:  # 单句仍然超长（表格/长列表）
                units.append(sentence[:size])
                sentence = sentence[size - overlap :]
            if len(buffer) + len(sentence) <= size:
                buffer += sentence
            else:
                if buffer:
                    units.append(buffer)
                buffer = sentence
        if buffer:
            units.append(buffer)

    chunks: list[str] = []
    buffer = ""
    for unit in units:
        if not buffer:
            buffer = unit
        elif len(buffer) + len(unit) + 1 <= size:
            buffer = f"{buffer}\n{unit}"
        else:
            chunks.append(buffer)
            # 重叠只取尾部，避免块首信息重复进两次
            tail = buffer[-overlap:] if overlap > 0 else ""
            buffer = f"{tail}\n{unit}".strip() if tail else unit
    if buffer:
        chunks.append(buffer)

    # 尾块过短则并入前一块，避免产生"只有一句话"的低信息块
    if len(chunks) >= 2 and len(chunks[-1]) < MIN_CHUNK:
        chunks[-2] = f"{chunks[-2]}\n{chunks[-1]}"
        chunks.pop()
    return [c.strip() for c in chunks if c.strip()]


def doc_title_of(markdown: str) -> str:
    """取一级标题作为文档标题；没有则返回空串，由调用方用文件名兜底。"""
    for line in markdown.splitlines():
        match = _MD_HEADING.match(line.strip())
        if match and len(match.group(1)) == 1:
            return match.group(2).strip()
    return ""


def chunk_markdown(
    markdown: str, *, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP
) -> list[str]:
    """按二级标题切块，每块自带「文档标题 · 小节标题」前缀。

    为什么不直接把全文按长度切：政策文档天然以小节为语义单元，
    "起算时间""运费承担"各自独立成块，向量不会被两个主题平均掉；
    前缀把标题信息带进向量，检索"运费谁出"时能命中"运费规则 · 运费承担方"。

    小节超过 size 时才退化为句子级滑窗（长表格、长清单）。
    """
    text = normalize(markdown)
    if not text:
        return []

    title = doc_title_of(text)
    sections: list[tuple[str, str]] = []
    current_heading = ""
    buffer: list[str] = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        match = _MD_HEADING.match(line)
        if match and len(match.group(1)) == 2:
            if buffer and any(buffer):
                sections.append((current_heading, "\n".join(buffer).strip()))
            current_heading = match.group(2).strip()
            buffer = []
            continue
        if match and len(match.group(1)) == 1:
            continue  # 一级标题已经作为前缀使用
        buffer.append(line)
    if buffer and any(buffer):
        sections.append((current_heading, "\n".join(buffer).strip()))

    if not sections:  # 没有二级标题：退回按长度切
        return chunk_text(text, size=size, overlap=overlap)

    chunks: list[str] = []
    for heading, body in sections:
        prefix = f"{title} · {heading}" if heading else title
        body = body.strip()
        if not body:
            continue
        if len(body) + len(prefix) + 1 <= size:
            chunks.append(f"{prefix}\n{body}")
            continue
        for piece in chunk_text(body, size=size - len(prefix) - 1, overlap=overlap):
            chunks.append(f"{prefix}\n{piece}")
    return [chunk for chunk in chunks if len(chunk) >= 40]

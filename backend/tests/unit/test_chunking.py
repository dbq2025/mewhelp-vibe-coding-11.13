"""分块与分词的纯函数测试。

这两块最容易"看起来对、实际把语义切碎"，因此用带标题的真实文档结构验证：
每块必须带「文档标题 · 小节标题」前缀，且覆盖全部小节。
"""

from app.rag.chunking import chunk_markdown, chunk_text, doc_title_of, normalize
from app.rag.segment import segment, to_tsquery

SAMPLE = """# 退换货总则

## 适用范围

本总则适用于平台自营及官方旗舰店销售的全部实物商品，虚拟商品另行公示。

## 时效要求

七天无理由退货须在签收后 7 个自然日内提交，以系统提交时间为准。

## 常见问题

问：赠品需要一起寄回吗？答：需要，赠品属于订单组成部分。
"""


def test_doc_title_extracts_h1() -> None:
    assert doc_title_of(SAMPLE) == "退换货总则"
    assert doc_title_of("没有标题的正文") == ""


def test_chunk_markdown_one_chunk_per_section_with_prefix() -> None:
    chunks = chunk_markdown(SAMPLE)
    assert len(chunks) == 3
    assert all(chunk.startswith("退换货总则 · ") for chunk in chunks)
    assert any("适用范围" in chunk for chunk in chunks)
    assert any("7 个自然日" in chunk for chunk in chunks)


def test_chunk_markdown_long_section_falls_back_to_window() -> None:
    long_body = "这是一句用于填充长度的话。" * 60
    text = f"# 长文档\n\n## 细则\n\n{long_body}"
    chunks = chunk_markdown(text, size=200, overlap=40)
    assert len(chunks) > 1
    # 上界 = size + 重叠 + MIN_CHUNK 尾块合并 + 标题前缀；断言上界是为了防"越切越长"
    assert all(len(chunk) <= 360 for chunk in chunks)
    assert all(chunk.startswith("长文档 · 细则") for chunk in chunks)
    assert all(len(chunk) > 60 for chunk in chunks)


def test_chunk_text_respects_size_and_merges_tail() -> None:
    text = "第一段内容。" * 30 + "\n\n" + "第二段内容。" * 30
    chunks = chunk_text(text, size=150, overlap=30)
    assert chunks
    assert all(len(chunk) <= 260 for chunk in chunks)


def test_normalize_collapses_blank_lines() -> None:
    assert normalize("a\n\n\n\nb   c") == "a\n\nb c"


def test_segment_produces_bigrams_and_drops_punctuation() -> None:
    tokens = segment("七天无理由退货，运费谁承担？").split()
    assert "七天" in tokens
    assert "运费" in tokens
    assert "，" not in " ".join(tokens)
    assert all("？" not in token for token in tokens)


def test_tsquery_is_injection_safe() -> None:
    query = to_tsquery("七天无理由' | & !:( 运费")
    assert "'" not in query
    assert "&" not in query and "!" not in query
    assert query

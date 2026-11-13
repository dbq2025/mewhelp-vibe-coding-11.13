"""检索评测（计划 P1 验收第 5 条：10 条 query 的 top3 人工命中 ≥ 8 条）。

评的是"检索能不能把正确的政策文档排进前三"，不是"回答好不好"——
后者要等 P2 有生成链路后再评测。指标口径：

- **hit@3**：top3 里出现期望文档标题即算命中；
- **MRR**：命中位置的倒数（第 1 位 1.0、第 2 位 0.5、第 3 位 0.33），衡量排序质量；
- **阈值存活率**：套用 `rag_max_distance` 后仍返回结果的 query 占比。
  这项若过低，说明阈值太严，Agent 会频繁回答"没查到"。

结果写入 `docs/eval.md`（用标记块替换，不覆盖其他阶段内容）。
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from app.core.config import get_settings
from app.infra.db.session import SessionFactory, dispose_engine
from app.rag.retriever import search

EVAL_FILE = Path(__file__).resolve().parents[2] / "docs" / "eval.md"
START_MARK = "<!-- rag-eval:start -->"
END_MARK = "<!-- rag-eval:end -->"


@dataclass(frozen=True, slots=True)
class Case:
    query: str
    expected_title: str
    note: str = ""


CASES: list[Case] = [
    Case("七天无理由的七天从签收还是发货开始算", "七天无理由退货细则", "起算时间是高频误答点"),
    Case("耳机一边没声音了算质量问题吗", "质量问题退换判定", "需区分质量与个人偏好"),
    Case("退款多久能到账", "退货流程与退款时效", "渠道差异"),
    Case("换货可以换成别的颜色吗", "换货政策", "同款同规格限制"),
    Case("耳机保修期是多长时间", "保修政策", "按品类不同"),
    Case("发票抬头开错了怎么重开", "发票换开与重开", "换开次数与时效"),
    Case("价保期是几天，降价了怎么补差价", "价格保护", "15 天 + 券形式返还"),
    Case("积分能抵多少钱", "会员积分", "100 积分抵 1 元"),
    Case("已经扣款了但订单显示未支付怎么办", "支付失败与重复扣款", "回调延迟处理"),
    Case("包裹显示已签收但是我根本没收到", "物流查询与异常处理", "代收与丢件判定"),
]


async def run_eval() -> dict[str, object]:
    settings = get_settings()
    rows: list[dict[str, object]] = []
    hits = 0
    survived = 0
    reciprocal = 0.0

    async with SessionFactory() as session:
        for case in CASES:
            chunks = await search(session, case.query, top_k=3, max_distance=1.0)
            titles = [chunk.doc_title for chunk in chunks]
            rank = titles.index(case.expected_title) + 1 if case.expected_title in titles else 0
            if rank:
                hits += 1
                reciprocal += 1.0 / rank
            # 阈值存活：换一个只保留阈值内结果的查询，看是否还有内容可引用
            kept = [c for c in chunks if c.distance <= settings.rag_max_distance]
            if kept:
                survived += 1
            rows.append(
                {
                    "query": case.query,
                    "expected": case.expected_title,
                    "top3": titles,
                    "rank": rank,
                    "distances": [round(chunk.distance, 4) for chunk in chunks],
                    "kept": len(kept),
                }
            )

    total = len(CASES)
    return {
        "rows": rows,
        "hit_at_3": hits,
        "total": total,
        "mrr": round(reciprocal / total, 3),
        "survival": survived,
        "threshold": settings.rag_max_distance,
        "top_k": settings.rag_top_k,
        "model": settings.embedding_model,
        "ran_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%SZ"),
    }


def render(result: dict[str, object]) -> str:
    rows: list[dict[str, object]] = result["rows"]  # type: ignore[assignment]
    lines = [
        START_MARK,
        "## RAG 检索评测（P1）",
        "",
        f"- 运行时间：{result['ran_at']}",
        f"- 模型：`{result['model']}`，top_k={result['top_k']}，距离阈值 {result['threshold']}",
        f"- **hit@3：{result['hit_at_3']}/{result['total']}**，MRR={result['mrr']}，"
        f"阈值内存活 {result['survival']}/{result['total']}",
        "",
        "| # | query | 期望文档 | top3 | 命中位次 | 距离 | 阈值内条数 |",
        "|---|---|---|---|---|---|---|",
    ]
    for index, row in enumerate(rows, start=1):
        top3 = " / ".join(row["top3"]) or "（空）"  # type: ignore[arg-type]
        rank = row["rank"] or "未命中"
        distances = ", ".join(f"{d:.3f}" for d in row["distances"])  # type: ignore[union-attr]
        lines.append(
            f"| {index} | {row['query']} | {row['expected']} | {top3} | "
            f"{rank} | {distances} | {row['kept']} |"
        )
    lines.extend(
        [
            "",
            "判定口径：top3 中出现期望文档标题即命中；距离越小越相关（余弦距离）。",
            END_MARK,
        ]
    )
    return "\n".join(lines)


def write_eval(section: str) -> Path:
    header = (
        "# 评测记录 · ecom-copilot\n\n"
        "> 每个阶段完成后追加一节，数字必须来自真实运行，禁止手填。\n\n"
    )
    if EVAL_FILE.exists():
        current = EVAL_FILE.read_text(encoding="utf-8")
        if START_MARK in current and END_MARK in current:
            before = current.split(START_MARK)[0]
            after = current.split(END_MARK, 1)[1]
            content = f"{before}{section}{after}"
        else:
            content = f"{current.rstrip()}\n\n{section}\n"
    else:
        content = f"{header}{section}\n"
    EVAL_FILE.parent.mkdir(parents=True, exist_ok=True)
    EVAL_FILE.write_text(content, encoding="utf-8")
    return EVAL_FILE


def main() -> None:
    parser = argparse.ArgumentParser(description="检索评测")
    parser.add_argument("--no-write", action="store_true", help="只打印，不写 docs/eval.md")
    args = parser.parse_args()

    async def runner() -> int:
        try:
            result = await run_eval()
        finally:
            await dispose_engine()
        section = render(result)
        print("\n".join(section.splitlines()[2:]))
        if not args.no_write:
            path = write_eval(section)
            print(f"\n已写入 {path}")
        hit = int(result["hit_at_3"])
        total = int(result["total"])
        print(f"结论：hit@3 = {hit}/{total}（门槛 8/10）")
        return 0 if hit >= 8 else 1

    raise SystemExit(asyncio.run(runner()))


if __name__ == "__main__":
    main()

"""运维看板聚合（P4）：把散在三张表里的运行数据压成一次响应。

为什么不在路由里写这些查询：`api` 层不允许直接查库（agent.md §2 铁律 3），
且这套口径要被 `scripts/eval.py` 与 `/admin/metrics` 共用，抽成 service 才能保证
"我看到的分位数"和"评测报告的分位数"是同一个算法。

分位数用 `percentile_cont`（连续分位，会线性插值）而不是自己取第 k 个：
样本只有几十条时，取第 k 个会让 p95 完全取决于某个离群值的位置。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.ratelimit import limiter
from app.infra.db.models.chat import Message
from app.infra.db.models.ops import AuditEvent, HandoffTicket, LlmUsage
from app.infra.db.models.order import AfterSale


@dataclass
class _Acc:
    counts: dict[str, int] = field(default_factory=dict)

    def add(self, key: str, value: int = 1) -> None:
        self.counts[key] = self.counts.get(key, 0) + value


async def _percentiles(session: AsyncSession, cutoff: datetime) -> dict[str, float]:
    row = (
        await session.execute(
            select(
                func.percentile_cont(0.5).within_group(Message.latency_ms),
                func.percentile_cont(0.95).within_group(Message.latency_ms),
                func.percentile_cont(0.99).within_group(Message.latency_ms),
            ).where(Message.role == "assistant", Message.created_at >= cutoff)
        )
    ).one()
    return {
        "p50": round(float(row[0] or 0), 1),
        "p95": round(float(row[1] or 0), 1),
        "p99": round(float(row[2] or 0), 1),
    }


def _cost_cny(prompt_tokens: int, completion_tokens: int) -> float:
    settings = get_settings()
    cost = (
        prompt_tokens / 1_000_000 * settings.llm_price_input_per_mtok
        + completion_tokens / 1_000_000 * settings.llm_price_output_per_mtok
    )
    return round(cost, 6)


async def collect(session: AsyncSession, *, window_hours: int | None = None) -> dict[str, Any]:
    settings = get_settings()
    hours = window_hours or settings.metrics_window_hours
    cutoff = datetime.now(UTC) - timedelta(hours=hours)

    # --- 轮次与状态 ---
    status_rows = (
        await session.execute(
            select(Message.status, func.count())
            .where(Message.role == "assistant", Message.created_at >= cutoff)
            .group_by(Message.status)
        )
    ).all()
    statuses = {str(row[0]): int(row[1]) for row in status_rows}
    turns = sum(statuses.values())

    latency = await _percentiles(session, cutoff)

    # --- LLM 计量与成本 ---
    llm_row = (
        await session.execute(
            select(
                func.count(),
                func.coalesce(func.sum(LlmUsage.prompt_tokens), 0),
                func.coalesce(func.sum(LlmUsage.completion_tokens), 0),
                func.count().filter(LlmUsage.ok.is_(False)),
            ).where(LlmUsage.created_at >= cutoff)
        )
    ).one()
    calls, prompt_tokens, completion_tokens, llm_errors = (int(v or 0) for v in llm_row)
    cost = _cost_cny(prompt_tokens, completion_tokens)

    # --- 意图分布 ---
    intent_rows = (
        await session.execute(
            select(Message.intent, Message.status, func.count())
            .where(Message.role == "assistant", Message.created_at >= cutoff)
            .group_by(Message.intent, Message.status)
        )
    ).all()
    intent_acc: dict[str, dict[str, int]] = {}
    for intent, status, count in intent_rows:
        label = str(intent or "unknown")
        bucket = intent_acc.setdefault(label, {"count": 0, "incomplete": 0})
        bucket["count"] += int(count)
        if str(status) != "ok":
            bucket["incomplete"] += int(count)

    # --- 工具调用（JSONB 里存的是本轮全部工具轨迹）---
    tool_rows = (
        (
            await session.execute(
                select(Message.tool_calls)
                .where(Message.role == "assistant", Message.created_at >= cutoff)
                .where(Message.tool_calls.is_not(None))
                .limit(2000)
            )
        )
        .scalars()
        .all()
    )
    tools = _Acc()
    tool_errors = _Acc()
    tool_total = 0
    for calls_json in tool_rows:
        for item in calls_json or []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "unknown")
            tool_total += 1
            tools.add(name)
            if item.get("ok") is False:
                tool_errors.add(name)
    tool_error_total = sum(tool_errors.counts.values())

    # --- 业务侧计数 ---
    after_sales_rows = (
        await session.execute(
            select(AfterSale.status, func.count())
            .where(AfterSale.created_at >= cutoff, AfterSale.source == "agent")
            .group_by(AfterSale.status)
        )
    ).all()
    handoff_rows = (
        await session.execute(
            select(HandoffTicket.status, func.count())
            .where(HandoffTicket.created_at >= cutoff)
            .group_by(HandoffTicket.status)
        )
    ).all()
    audit_denied = int(
        await session.scalar(
            select(func.count()).where(
                AuditEvent.created_at >= cutoff, AuditEvent.result == "denied"
            )
        )
        or 0
    )

    return {
        "windowHours": hours,
        "turns": {
            "total": turns,
            "ok": statuses.get("ok", 0),
            "incomplete": statuses.get("incomplete", 0),
            "blocked": statuses.get("blocked", 0),
            "successRate": round(statuses.get("ok", 0) / turns, 4) if turns else 0.0,
        },
        "latencyMs": latency,
        "llm": {
            "calls": calls,
            "errors": llm_errors,
            "errorRate": round(llm_errors / calls, 4) if calls else 0.0,
            "promptTokens": prompt_tokens,
            "completionTokens": completion_tokens,
            "costCny": cost,
            "costPerTurnCny": round(cost / turns, 6) if turns else 0.0,
        },
        "intent": [
            {
                "intent": name,
                "count": values["count"],
                "incomplete": values["incomplete"],
                "share": round(values["count"] / turns, 4) if turns else 0.0,
            }
            for name, values in sorted(intent_acc.items(), key=lambda kv: -kv[1]["count"])
        ],
        "tools": {
            "calls": tool_total,
            "errors": tool_error_total,
            "errorRate": round(tool_error_total / tool_total, 4) if tool_total else 0.0,
            "top": [
                {"name": name, "count": count}
                for name, count in sorted(tools.counts.items(), key=lambda kv: -kv[1])[:6]
            ],
        },
        "afterSales": {
            "byStatus": {str(k): int(v) for k, v in after_sales_rows},
            "total": sum(int(v) for _, v in after_sales_rows),
        },
        "handoff": {
            "byStatus": {str(k): int(v) for k, v in handoff_rows},
            "total": sum(int(v) for _, v in handoff_rows),
        },
        "security": {
            "auditDenied": audit_denied,
            "throttledLastMinute": limiter.stats.last_minute(),
            "throttledTotal": limiter.stats.total,
            "rateLimitPerMinute": limiter.limit,
        },
    }

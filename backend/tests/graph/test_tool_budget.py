"""工具步数上限（P3 验收第 3 条）：超限就地降级，不是抛异常也不是死循环。

为什么单独测：这条逻辑一旦退化成异常，整轮对话会 500；
退化成"继续调"，就会出现一个请求打十几次数据库/检索的放大效应。
"""

from __future__ import annotations

from uuid import uuid4

from app.agent.nodes.actions import _run_tool
from app.agent.runtime import RunContext, use_context
from app.core.config import get_settings
from app.infra.db.session import SessionFactory


async def test_tool_budget_exceeded_degrades() -> None:
    budget = get_settings().max_tool_steps
    async with SessionFactory() as session:
        ctx = RunContext(session=session, session_id=str(uuid4()), trace_id="test-budget")
        ctx.tool_steps = budget  # 假装已经用满
        with use_context(ctx):
            result = await _run_tool(session, "search_products", {"keyword": "耳机", "limit": 1})

    assert result.ok is False
    assert result.error_code == "4008"
    assert str(budget) in result.summary


async def test_tool_budget_counts_up() -> None:
    async with SessionFactory() as session:
        ctx = RunContext(session=session, session_id=str(uuid4()), trace_id="test-budget-2")
        with use_context(ctx):
            await _run_tool(session, "search_products", {"keyword": "耳机", "limit": 1})
            await _run_tool(session, "search_products", {"keyword": "充电器", "limit": 1})
        assert ctx.tool_steps == 2

"""节点：输入守卫。"""

from __future__ import annotations

from app.agent.guard import check_input
from app.agent.runtime import get_context
from app.agent.state import GraphState, Route


async def guard_node(state: GraphState) -> dict[str, object]:
    ctx = get_context()
    result = check_input(state.get("user_text", ""), session_id=ctx.session_id)
    if result.allowed:
        return {"blocked": False, "blocked_reason": None}

    # 拦截后不调模型：这类输入送进 prompt 只会让它更"听话"
    return {
        "blocked": True,
        "blocked_reason": result.reason,
        "route": Route.BLOCKED,
        "intent": "blocked",
        "confidence": 1.0,
        "draft": result.message,
    }


def guard_route(state: GraphState) -> str:
    return "blocked" if state.get("blocked") else "continue"

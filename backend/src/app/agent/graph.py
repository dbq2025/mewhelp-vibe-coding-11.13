"""LangGraph 主图装配（计划 4.1）。

    START → guard ─┬─ blocked ─────────────────────────→ static → END
                   └─ continue → understand ─┬─ clarify → clarify → static
                                             ├─ handoff → handoff → static
                                             ├─ sales_agent ─┐
                                             ├─ order_flow ──┼→ compose → END
                                             ├─ retrieve ────┤
                                             └─ chitchat ────┘

图只负责"这一轮怎么走"，不持有任何跨轮状态：每轮由 runner 从 DB 重建 state。
这样"图崩溃了"和"数据丢了"是两件可以分别排查的事。
"""

from __future__ import annotations

from functools import lru_cache

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.agent.nodes.actions import (
    clarify_node,
    handoff_node,
    order_node,
    retrieve_node,
    sales_node,
)
from app.agent.nodes.compose import compose_node, static_node
from app.agent.nodes.guard import guard_node, guard_route
from app.agent.nodes.understand import route_after_understand, understand_node
from app.agent.state import GraphState, Route


def build_graph() -> StateGraph[GraphState]:
    graph: StateGraph[GraphState] = StateGraph(GraphState)

    graph.add_node("guard", guard_node)
    graph.add_node("understand", understand_node)
    graph.add_node("sales_agent", sales_node)
    graph.add_node("order_flow", order_node)
    graph.add_node("retrieve", retrieve_node)
    graph.add_node("handoff", handoff_node)
    graph.add_node("clarify", clarify_node)
    graph.add_node("compose", compose_node)
    graph.add_node("static", static_node)

    graph.add_edge(START, "guard")
    graph.add_conditional_edges(
        "guard",
        guard_route,
        {"blocked": "static", "continue": "understand"},
    )
    graph.add_conditional_edges(
        "understand",
        route_after_understand,
        {
            Route.CLARIFY.value: "clarify",
            Route.HANDOFF.value: "handoff",
            Route.SALES.value: "sales_agent",
            Route.ORDER.value: "order_flow",
            Route.RETRIEVE.value: "retrieve",
            Route.CHITCHAT.value: "compose",
        },
    )
    graph.add_edge("clarify", "static")
    graph.add_edge("handoff", "static")
    graph.add_edge("sales_agent", "compose")
    graph.add_edge("order_flow", "compose")
    graph.add_edge("retrieve", "compose")
    graph.add_edge("compose", END)
    graph.add_edge("static", END)
    return graph


@lru_cache(maxsize=1)
def get_graph() -> CompiledStateGraph[GraphState, None, GraphState, GraphState]:
    return build_graph().compile()

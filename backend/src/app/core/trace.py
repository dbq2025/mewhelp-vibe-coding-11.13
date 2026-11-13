"""trace_id 贯穿：请求入口生成，写进 contextvar 与响应头，日志自动带上。

不做分布式追踪（本项目单进程），但要保证"用户报一个问题 → 我能按 traceId 捞出
这一轮的日志、工具调用与 LLM 计费"，这是可观测性的最低要求。
"""

from contextvars import ContextVar
from uuid import uuid4

import structlog
from starlette.middleware.base import RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

TRACE_HEADER = "X-Trace-Id"
_trace_id: ContextVar[str] = ContextVar("trace_id", default="")


def new_trace_id() -> str:
    return uuid4().hex[:16]


def get_trace_id() -> str:
    return _trace_id.get()


def set_trace_id(trace_id: str) -> None:
    _trace_id.set(trace_id)
    structlog.contextvars.bind_contextvars(trace_id=trace_id)


async def trace_middleware(request: Request, call_next: RequestResponseEndpoint) -> Response:
    trace_id = request.headers.get(TRACE_HEADER) or new_trace_id()
    set_trace_id(trace_id)
    try:
        response = await call_next(request)
    finally:
        structlog.contextvars.unbind_contextvars("trace_id")
    response.headers[TRACE_HEADER] = trace_id
    return response

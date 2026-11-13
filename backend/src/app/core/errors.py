"""业务异常与错误码（docs/api.md §4 与计划 6.4 的唯一来源）。

规则：业务代码只 raise AppError 子类，不自己拼 HTTP 状态码；
异常处理器统一转成 envelope，保证前端只需处理一种错误结构。
"""

from http import HTTPStatus

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import get_logger
from app.core.trace import get_trace_id

logger = get_logger(__name__)

# 错误码：4 位整数，按域分段（agent.md §5）
CODE_OK = 0
CODE_INVALID_PARAM = 1001
CODE_UNAUTHENTICATED = 2001
CODE_FORBIDDEN = 2003
CODE_NOT_FOUND = 2004
CODE_LLM_TIMEOUT = 3001
CODE_UPSTREAM_RATE_LIMIT = 3002
CODE_BLOCKED = 3003
CODE_TOOL_BUDGET = 4008
CODE_SESSION_BUSY = 4009
# HTTP 层限流（中间件直接返回，不走异常处理器；码值仍登记在此，前端只需认它）
CODE_RATE_LIMITED = 4029
CODE_INTERNAL = 5000


class AppError(Exception):
    """所有可预期的业务异常基类。"""

    def __init__(
        self,
        code: int = CODE_INTERNAL,
        message: str = "内部错误",
        http_status: int = HTTPStatus.INTERNAL_SERVER_ERROR,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = int(http_status)


class InvalidParamError(AppError):
    def __init__(self, message: str = "参数校验失败") -> None:
        super().__init__(CODE_INVALID_PARAM, message, HTTPStatus.BAD_REQUEST)


class UnauthenticatedError(AppError):
    def __init__(self, message: str = "未认证") -> None:
        super().__init__(CODE_UNAUTHENTICATED, message, HTTPStatus.UNAUTHORIZED)


class ForbiddenError(AppError):
    """越权与"资源不存在"合并为同一码，防订单号探测（计划 5.3）。"""

    def __init__(self, message: str = "资源不存在或无权访问") -> None:
        super().__init__(CODE_FORBIDDEN, message, HTTPStatus.FORBIDDEN)


class NotFoundError(AppError):
    def __init__(self, message: str = "资源不存在") -> None:
        super().__init__(CODE_NOT_FOUND, message, HTTPStatus.NOT_FOUND)


class SessionBusyError(AppError):
    def __init__(self, message: str = "上一条消息还在处理中，请稍候") -> None:
        super().__init__(CODE_SESSION_BUSY, message, HTTPStatus.CONFLICT)


def _envelope(code: int, message: str, data: object | None = None) -> dict[str, object]:
    return {"code": code, "message": message, "data": data, "traceId": get_trace_id()}


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        logger.warning("app_error", code=exc.code, message=exc.message)
        return JSONResponse(status_code=exc.http_status, content=_envelope(exc.code, exc.message))

    @app.exception_handler(RequestValidationError)
    async def _handle_validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        loc = ".".join(str(p) for p in first.get("loc", ()) if p != "body")
        detail = f"{loc}: {first.get('msg', '参数不合法')}" if loc else "参数不合法"
        return JSONResponse(
            status_code=HTTPStatus.BAD_REQUEST,
            content=_envelope(CODE_INVALID_PARAM, detail),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _handle_http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = CODE_NOT_FOUND if exc.status_code == HTTPStatus.NOT_FOUND else CODE_INTERNAL
        return JSONResponse(status_code=exc.status_code, content=_envelope(code, str(exc.detail)))

    @app.exception_handler(Exception)
    async def _handle_unexpected(_: Request, exc: Exception) -> JSONResponse:
        # 只有真正未预期的问题才走这里；堆栈进日志，不返回给客户端
        logger.exception("unhandled_error", error=repr(exc))
        return JSONResponse(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            content=_envelope(CODE_INTERNAL, "服务内部错误，请稍后重试"),
        )

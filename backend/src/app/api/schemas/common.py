"""统一响应 envelope（agent.md §6）：禁止裸对象/裸数组。

前端只需处理一种成功结构 + 一种错误结构，减少适配成本。
用 PEP 695 泛型语法（Python 3.13），避免 TypeVar 样板。
"""

from pydantic import BaseModel, Field

from app.core.trace import get_trace_id


class ApiResponse[T](BaseModel):
    code: int = 0
    message: str = "ok"
    data: T | None = None
    traceId: str = ""


class PageMeta(BaseModel):
    nextCursor: str | None = None
    hasMore: bool = False
    total: int | None = None


class PageData[T](BaseModel):
    items: list[T] = Field(default_factory=list)
    page: PageMeta = Field(default_factory=PageMeta)


def ok[T](data: T, message: str = "ok") -> ApiResponse[T]:
    return ApiResponse[T](code=0, message=message, data=data, traceId=get_trace_id())

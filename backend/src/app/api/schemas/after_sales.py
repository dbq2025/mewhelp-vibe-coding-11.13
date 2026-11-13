"""售后与转人工接口的请求/响应体（api.md §2.7）。

字段命名沿用 camelCase（与前端/契约一致），类型里不出现 ORM 对象。
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

AfterSaleType = Literal["return", "exchange", "repair"]
HandoffStatus = Literal["accepted", "closed"]


class AfterSaleCreateRequest(BaseModel):
    orderNo: str = Field(min_length=6, max_length=32, description="订单号")
    type: AfterSaleType = Field(description="return / exchange / repair")
    reason: str = Field(default="", max_length=500, description="申请原因，可选")
    phoneTail: str | None = Field(
        default=None,
        max_length=4,
        description="游客查单用；本接口要求登录，保留字段是为了与订单接口口径一致",
    )


class AfterSaleOut(BaseModel):
    ticketNo: str
    orderNo: str
    type: str
    typeLabel: str
    status: str
    statusLabel: str
    reason: str = ""
    createdAt: datetime | None = None
    # 本次调用是否真的新建了单（false = 命中了已有未完结单，幂等返回）
    created: bool = True


class HandoffCreateRequest(BaseModel):
    sessionId: str = Field(min_length=1, max_length=64)
    reason: str = Field(default="", max_length=200)


class HandoffOut(BaseModel):
    ticketNo: str
    sessionId: str
    status: str
    statusLabel: str
    reason: str = ""
    createdAt: datetime | None = None
    created: bool = True


class HandoffTransitionRequest(BaseModel):
    status: HandoffStatus = Field(description="accepted（客服接入）或 closed（结束）")

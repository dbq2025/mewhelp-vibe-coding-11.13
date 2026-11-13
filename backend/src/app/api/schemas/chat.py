"""会话与对话的对外 DTO（字段与 docs/api.md §2.3/§2.4 一一对应）。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class SessionOut(BaseModel):
    id: UUID
    title: str
    createdAt: datetime
    updatedAt: datetime


class SessionCreateIn(BaseModel):
    title: str | None = Field(default=None, max_length=100)


class SessionPatchIn(BaseModel):
    title: str = Field(min_length=1, max_length=100)


class MessageOut(BaseModel):
    id: int
    role: Literal["user", "assistant"]
    content: str
    status: str
    intent: str | None = None
    citations: list[dict[str, Any]] = Field(default_factory=list)
    tools: list[dict[str, Any]] = Field(default_factory=list)
    latencyMs: int | None = None
    createdAt: datetime


class ChatStreamIn(BaseModel):
    sessionId: UUID
    message: str = Field(min_length=1, max_length=2000)
    # 前端生成的一次性 id：网络重试时同一个 id 不会重复计费/重复落库
    clientMsgId: str | None = Field(default=None, max_length=64)


class ChatReplayOut(BaseModel):
    """幂等重放时返回已有结果（非流式调用方可用）。"""

    messageId: int
    content: str
    status: str
    citations: list[dict[str, Any]] = Field(default_factory=list)


class MessageFeedbackIn(BaseModel):
    rating: Literal[1, -1]
    comment: str | None = Field(default=None, max_length=500)

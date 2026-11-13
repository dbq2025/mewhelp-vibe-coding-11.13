"""运维看板：`/admin/metrics`（P4）。

鉴权用**静态口令**而不是用户 JWT，因为这不是"某个用户的功能"，而是"运维在看服务器"：
- 口令为空 → 端点返回 404，不暴露"这里有个后台"（默认部署就是关的）；
- 口令用 `secrets.compare_digest` 比较，避免计时侧信道；
- 只返回聚合值，**不含任何用户标识、订单号、手机号**——看板不该成为新的泄漏面。
"""

from __future__ import annotations

import secrets
from typing import Annotated, Any

from fastapi import APIRouter, Header, Query

from app.api.schemas.common import ApiResponse, ok
from app.core.config import get_settings
from app.core.deps import DbSession
from app.core.errors import ForbiddenError, NotFoundError
from app.domain.services import metrics as metrics_service

router = APIRouter(tags=["admin"], prefix="/admin")

_ADMIN_HEADER = "X-Admin-Token"


def _require_admin(token: str | None) -> None:
    expected = get_settings().admin_token
    if not expected:
        # 未配置 = 功能未启用。用 404 而不是 403，避免向扫描器确认端点存在
        raise NotFoundError("资源不存在")
    if token is None or not secrets.compare_digest(token, expected):
        raise ForbiddenError("无权访问")


@router.get(
    "/metrics",
    response_model=ApiResponse[dict[str, Any]],
    summary="运行指标（需 X-Admin-Token）",
)
async def admin_metrics(
    session: DbSession,
    x_admin_token: Annotated[str | None, Header(alias=_ADMIN_HEADER)] = None,
    hours: Annotated[int, Query(ge=1, le=168)] = 0,
) -> ApiResponse[dict[str, Any]]:
    _require_admin(x_admin_token)
    data = await metrics_service.collect(session, window_hours=hours or None)
    return ok(data)

"""售后与转人工路由（api.md §2.7）。

为什么这两个 POST 都要求登录：
建单是写操作，会进入真实的退款/客服流程。游客能建单意味着任何人都能拿别人的
订单号刷工单（虽然要过鉴权，但至少要有账号可追溯）。查单可以游客，建单不行。

鉴权口径与订单一致：越权与不存在同码 2003，拒绝落 `audit_events`。
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, status

from app.api.deps import CurrentUser
from app.api.schemas.after_sales import (
    AfterSaleCreateRequest,
    AfterSaleOut,
    HandoffCreateRequest,
    HandoffOut,
    HandoffTransitionRequest,
)
from app.api.schemas.common import ApiResponse, ok
from app.core.deps import DbSession
from app.core.errors import ForbiddenError, InvalidParamError, NotFoundError
from app.core.trace import get_trace_id
from app.domain.policies.authz import assert_order_access
from app.domain.services import after_sales as as_service
from app.domain.services import handoff as handoff_service
from app.domain.services import orders as order_service

router = APIRouter(tags=["after-sales"])


def _ticket_out(ticket: object, created: bool) -> AfterSaleOut:
    from app.infra.db.models.order import AfterSale

    assert isinstance(ticket, AfterSale)
    return AfterSaleOut(
        ticketNo=ticket.ticket_no,
        orderNo=ticket.order_no,
        type=ticket.type,
        typeLabel=as_service.TYPE_LABELS.get(ticket.type, ticket.type),
        status=ticket.status,
        statusLabel=as_service.STATUS_LABELS.get(ticket.status, ticket.status),
        reason=ticket.reason or "",
        createdAt=ticket.created_at,
        created=created,
    )


@router.post(
    "/after-sales",
    response_model=ApiResponse[AfterSaleOut],
    status_code=status.HTTP_201_CREATED,
    summary="申请售后（幂等）",
)
async def create_after_sale(
    payload: AfterSaleCreateRequest,
    user: CurrentUser,
    session: DbSession,
) -> ApiResponse[AfterSaleOut]:
    """前端直接提交售后申请（对话里走二次确认后也调用同一个 service）。

    幂等：同一订单同一类型已有未完结单时返回那张（`created=false`，HTTP 仍 201），
    不重复建单、不重复触发退款流程。
    """
    order = await order_service.get_order_detail(session, payload.orderNo)
    checked = await assert_order_access(
        session,
        order,
        order_no=payload.orderNo,
        user=user,
        phone_tail=payload.phoneTail,
        actor=f"user:{user.id}",
        trace_id=get_trace_id(),
    )
    verdict = as_service.check_eligibility(checked, payload.type, payload.reason)
    if not verdict.ok:
        raise InvalidParamError(verdict.hint)

    ticket, created = await as_service.create_ticket(
        session,
        order=checked,
        user_id=user.id,
        kind=payload.type,
        reason=payload.reason,
        source="api",
    )
    return ok(_ticket_out(ticket, created))


@router.get(
    "/after-sales",
    response_model=ApiResponse[list[AfterSaleOut]],
    summary="我的售后单",
)
async def list_my_after_sales(
    user: CurrentUser,
    session: DbSession,
) -> ApiResponse[list[AfterSaleOut]]:
    tickets = await as_service.list_user_tickets(session, user_id=user.id)
    return ok([_ticket_out(ticket, False) for ticket in tickets])


@router.post(
    "/handoff",
    response_model=ApiResponse[HandoffOut],
    status_code=status.HTTP_201_CREATED,
    summary="转人工（幂等）",
)
async def create_handoff(
    payload: HandoffCreateRequest,
    user: CurrentUser,
    session: DbSession,
) -> ApiResponse[HandoffOut]:
    from app.domain.services import sessions as session_service

    try:
        session_uuid = UUID(payload.sessionId)
    except ValueError as exc:
        raise InvalidParamError("sessionId 不合法") from exc

    chat = await session_service.get_owned_session(
        session, session_id=session_uuid, user_id=user.id
    )
    ticket, created = await handoff_service.create_ticket(
        session,
        session_id=chat.id,
        user_id=user.id,
        reason=payload.reason,
    )
    await session_service.set_handoff_status(session, session_id=chat.id, status=ticket.status)
    return ok(
        HandoffOut(
            ticketNo=ticket.ticket_no,
            sessionId=str(ticket.session_id),
            status=ticket.status,
            statusLabel=handoff_service.STATUS_LABELS.get(ticket.status, ticket.status),
            reason=ticket.reason or "",
            createdAt=ticket.created_at,
            created=created,
        )
    )


@router.patch(
    "/handoff/{ticket_no}",
    response_model=ApiResponse[HandoffOut],
    summary="更新转人工工单状态（坐席侧调用）",
)
async def update_handoff(
    ticket_no: str,
    payload: HandoffTransitionRequest,
    user: CurrentUser,
    session: DbSession,
) -> ApiResponse[HandoffOut]:
    """状态机：pending → accepted → closed，不允许回退。

    本期不做坐席端 UI，接口先留着给 P4 的客服工作台与联调脚本用；
    归属校验按"工单必须属于当前用户"实现，坐席账号体系上线后改为角色判定。
    """
    ticket = await handoff_service.get_by_no(session, ticket_no)
    if ticket is None or ticket.user_id != user.id:
        raise NotFoundError("工单不存在")
    if ticket.user_id is None:
        raise ForbiddenError("无权操作该工单")

    await handoff_service.transition(session, ticket=ticket, to_status=payload.status)
    from app.domain.services import sessions as session_service

    await session_service.set_handoff_status(
        session, session_id=ticket.session_id, status=ticket.status
    )
    return ok(
        HandoffOut(
            ticketNo=ticket.ticket_no,
            sessionId=str(ticket.session_id),
            status=ticket.status,
            statusLabel=handoff_service.STATUS_LABELS.get(ticket.status, ticket.status),
            reason=ticket.reason or "",
            createdAt=ticket.created_at,
            created=False,
        )
    )

"""订单访问控制（计划 5.3，安全基线）。

两条铁律：
1. **判定在服务端、条件在 SQL 层**：登录用户查单直接 `order.user_id == user.id`，
   不靠"先查出来再比对"这种容易被后续重构绕过的写法。
2. **越权与不存在同码**（2003）：返回 404 等于告诉攻击者"这个单号存在"，
   订单号是顺序可枚举的，必须合并。

拒绝时必须落 `audit_events`——这是 P4 对抗集统计"越权泄漏 0/10"的数据源。
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ForbiddenError
from app.infra.db.models.ops import AuditEvent
from app.infra.db.models.order import Order
from app.infra.db.models.user import User

ACTION_ORDER_READ = "order.read"


async def _deny(
    session: AsyncSession,
    *,
    actor: str,
    target: str,
    trace_id: str,
    reason: str,
) -> None:
    session.add(
        AuditEvent(
            trace_id=trace_id,
            actor=actor,
            action=ACTION_ORDER_READ,
            target=target,
            result="denied",
            meta={"reason": reason},
        )
    )
    # 这里必须 commit：异常抛出后请求会话会回滚，审计会一起丢掉
    await session.commit()


async def assert_order_access(
    session: AsyncSession,
    order: Order | None,
    *,
    order_no: str,
    user: User | None,
    phone_tail: str | None,
    actor: str,
    trace_id: str,
) -> Order:
    """通过则返回订单，否则写审计并抛 2003。"""
    if order is None:
        await _deny(session, actor=actor, target=order_no, trace_id=trace_id, reason="not_found")
        raise ForbiddenError()

    if user is not None:
        if order.user_id != user.id:
            await _deny(
                session, actor=actor, target=order_no, trace_id=trace_id, reason="not_owner"
            )
            raise ForbiddenError()
        return order

    # 游客路径：只允许"订单号 + 手机尾号 4 位"双因子
    if phone_tail and order.receiver_phone_tail == phone_tail:
        return order

    await _deny(
        session,
        actor=actor,
        target=order_no,
        trace_id=trace_id,
        reason="guest_tail_mismatch" if phone_tail else "guest_without_tail",
    )
    raise ForbiddenError()

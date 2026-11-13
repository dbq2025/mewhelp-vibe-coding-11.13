"""健康检查：不只探进程活着，还要探 DB 与向量扩展是否真能用。

生产事故里"服务起来了但连不上库"最常见，所以 /health 会实际打一次 SQL，
并用一次向量距离运算验证 pgvector 真的可执行（而不是只看扩展是否存在）。
"""

from fastapi import APIRouter, Response, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.common import ApiResponse, ok
from app.core.config import get_settings
from app.core.logging import get_logger
from app.infra.db.session import SessionFactory

router = APIRouter(tags=["infra"])
logger = get_logger(__name__)

VECTOR_PROBE_SQL = "select '[1,2,3]'::vector <-> '[1,2,4]'::vector"


class HealthData(BaseModel):
    status: str
    db: str
    vector: str
    vectorVersion: str | None = None
    version: str
    env: str


async def _probe(session: AsyncSession) -> tuple[str, str, str | None]:
    try:
        await session.execute(text("select 1"))
    except SQLAlchemyError as exc:
        logger.error("health_db_unavailable", error=repr(exc))
        return "down", "unknown", None

    try:
        version = (
            await session.execute(
                text("select extversion from pg_extension where extname = 'vector'")
            )
        ).scalar_one_or_none()
        if version is None:
            logger.error("health_vector_missing")
            return "ok", "missing", None
        await session.execute(text(VECTOR_PROBE_SQL))
        return "ok", "ok", str(version)
    except SQLAlchemyError as exc:
        logger.error("health_vector_broken", error=repr(exc))
        return "ok", "broken", None


@router.get("/health", response_model=ApiResponse[HealthData], summary="健康检查")
async def health(response: Response) -> ApiResponse[HealthData]:
    """**不通过 DbSession 依赖**：连不上库时依赖注入本身就会抛异常，
    那样 /health 会变成 500「服务内部错误」，监控和演示都看不出是库挂了。
    自己开会话 + 兜住异常，才能稳定返回 503 + db=down。
    """
    settings = get_settings()
    try:
        async with SessionFactory() as session:
            db_status, vector_status, vector_version = await _probe(session)
    except (SQLAlchemyError, OSError) as exc:
        logger.error("health_session_unavailable", error=repr(exc))
        db_status, vector_status, vector_version = "down", "unknown", None

    healthy = db_status == "ok" and vector_status == "ok"
    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return ok(
        HealthData(
            status="ok" if healthy else "degraded",
            db=db_status,
            vector=vector_status,
            vectorVersion=vector_version,
            version=settings.app_version,
            env=settings.env,
        )
    )

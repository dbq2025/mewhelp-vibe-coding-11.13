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
from app.core.deps import DbSession
from app.core.logging import get_logger

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
async def health(response: Response, session: DbSession) -> ApiResponse[HealthData]:
    settings = get_settings()
    db_status, vector_status, vector_version = await _probe(session)
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

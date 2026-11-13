"""服务元信息：前端启动时用它确认后端版本与接口前缀，避免前后端契约漂移。"""

from fastapi import APIRouter
from pydantic import BaseModel

from app.api.schemas.common import ApiResponse, ok
from app.core.config import get_settings

router = APIRouter(tags=["meta"])


class MetaData(BaseModel):
    name: str
    version: str
    apiPrefix: str
    env: str


@router.get("/meta", response_model=ApiResponse[MetaData], summary="服务元信息")
async def meta() -> ApiResponse[MetaData]:
    settings = get_settings()
    return ok(
        MetaData(
            name=settings.app_name,
            version=settings.app_version,
            apiPrefix=settings.api_prefix,
            env=settings.env,
        )
    )

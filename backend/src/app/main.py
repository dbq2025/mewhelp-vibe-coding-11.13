"""应用装配：中间件、异常处理、路由挂载。

分层约束（agent.md §2）：main 只做装配，不允许出现业务逻辑。
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.api.routers import health
from app.core.config import get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.core.trace import TRACE_HEADER, trace_middleware
from app.infra.db.session import dispose_engine

settings = get_settings()
configure_logging(settings)
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    logger.info("app_start", env=settings.env, version=settings.app_version)
    try:
        yield
    finally:
        await dispose_engine()
        logger.info("app_stop")


def create_app() -> FastAPI:
    app = FastAPI(
        title="ecom-copilot API",
        version=settings.app_version,
        description="电商智能客服 Agent 服务",
        lifespan=lifespan,
    )

    # 先加 trace，再加 CORS：Starlette 后加的在最外层，
    # 这样异常响应也能带上 CORS 头（否则前端只能看到 "网络错误"）。
    app.middleware("http")(trace_middleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=[TRACE_HEADER],
    )

    register_exception_handlers(app)

    app.include_router(health.router)
    app.include_router(api_router, prefix=settings.api_prefix)
    return app


app = create_app()

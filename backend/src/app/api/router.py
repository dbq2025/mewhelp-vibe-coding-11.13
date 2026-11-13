"""API 路由汇总。新增业务路由只在此处注册，main.py 不再逐条 include。"""

from fastapi import APIRouter

from app.api.routers import meta

api_router = APIRouter()
api_router.include_router(meta.router)

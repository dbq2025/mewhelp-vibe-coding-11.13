"""API 路由汇总。新增业务路由只在此处注册，main.py 不再逐条 include。"""

from fastapi import APIRouter

from app.api.routers import admin, after_sales, auth, chat, meta, orders, products

api_router = APIRouter()
api_router.include_router(meta.router)
api_router.include_router(auth.router)
api_router.include_router(products.router)
api_router.include_router(orders.router)
api_router.include_router(chat.router)
api_router.include_router(after_sales.router)
api_router.include_router(admin.router)

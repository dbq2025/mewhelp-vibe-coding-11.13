"""模型汇总导出。Alembic 的 target_metadata 依赖这里 import 全部模型，
少 import 一个模块，autogenerate 就会漏表（且不会报错）。
"""

from app.infra.db.base import Base
from app.infra.db.models.catalog import Category, Product
from app.infra.db.models.chat import ChatSession, Message, SessionState
from app.infra.db.models.kb import EMBEDDING_DIM, KbChunk, KbDoc
from app.infra.db.models.ops import AuditEvent, HandoffTicket, LlmUsage
from app.infra.db.models.order import AfterSale, Order, OrderItem, Shipment
from app.infra.db.models.user import User

__all__ = [
    "EMBEDDING_DIM",
    "AfterSale",
    "AuditEvent",
    "Base",
    "Category",
    "ChatSession",
    "HandoffTicket",
    "KbChunk",
    "KbDoc",
    "LlmUsage",
    "Message",
    "Order",
    "OrderItem",
    "Product",
    "SessionState",
    "Shipment",
    "User",
]

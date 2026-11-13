"""同会话串行化。

为什么不用 `pg_advisory_xact_lock`（计划 4.7 的原方案）：
本轮的写库分多次提交（用户消息 → 工具审计 → 助手消息），
而 `xact` 锁在每次 commit 就释放，挡不住整轮并发；`pg_advisory_lock`（会话级）
又依赖"同一连接"，SQLAlchemy 在 commit 后会把连接还回池子，锁会静默丢失。
两种都比"看起来有锁"更危险。

因此 P2 用进程内锁，语义明确：单实例串行、排队超 `session_lock_wait_seconds` 返回 409。
多实例部署时必须换 Redis 分布式锁——这条和限流器同源，已记在计划偏差表里。
"""

from __future__ import annotations

import asyncio

_locks: dict[str, asyncio.Lock] = {}


def _lock_of(session_id: str) -> asyncio.Lock:
    lock = _locks.get(session_id)
    if lock is None:
        lock = asyncio.Lock()
        _locks[session_id] = lock
    return lock


async def acquire(session_id: str, *, wait_seconds: float) -> bool:
    """返回 True 表示拿到锁；False 表示排队超时（调用方回 409）。"""
    lock = _lock_of(session_id)
    try:
        await asyncio.wait_for(lock.acquire(), timeout=wait_seconds)
        return True
    except TimeoutError:
        return False


def release(session_id: str) -> None:
    lock = _locks.get(session_id)
    if lock is None:
        return
    if lock.locked():
        lock.release()
    if not lock.locked():
        _locks.pop(session_id, None)

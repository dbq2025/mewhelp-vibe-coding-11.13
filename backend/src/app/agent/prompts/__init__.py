"""Prompt 分层加载（计划 4.5）。

prompt 带版本目录（`v1/`），改动时新建 `v2/` 而不是原地改——
这样"改了 prompt 指标掉了"能一眼定位是哪一版，也便于 A/B。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

PROMPT_DIR = Path(__file__).parent
DEFAULT_VERSION = "v1"


@lru_cache(maxsize=16)
def load(name: str, version: str = DEFAULT_VERSION) -> str:
    path = PROMPT_DIR / version / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"prompt 不存在: {path}")
    return path.read_text(encoding="utf-8").strip()


def system_prompt() -> str:
    """角色 + 业务铁律，两段拼装成 system message。"""
    return f"{load('role')}\n\n## 铁律\n\n{load('rules')}"

"""应用配置：唯一的环境变量入口。

约定（agent.md §1）：所有魔法值（上限、超时、步数）集中在 Settings 里，
业务代码通过 `get_settings()` 读取，不在函数体里散落字面量。
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- 应用 ---
    app_name: str = "ecom-copilot"
    app_version: str = "0.1.0"
    env: str = "local"
    log_level: str = "INFO"
    log_json: bool = False
    api_prefix: str = "/api/v1"
    cors_origins: list[str] = Field(default=["http://localhost:5173", "http://127.0.0.1:5173"])

    # --- 数据库 ---
    pg_dsn: str = "postgresql+asyncpg://app:app_dev_pwd@127.0.0.1:5433/ecom"
    db_pool_size: int = 5
    db_max_overflow: int = 5
    db_echo: bool = False

    # --- 鉴权 ---
    # 仅本地开发默认值；生产必须通过 JWT_SECRET 环境变量覆盖（.env.example 有说明）
    jwt_secret: str = "dev-only-change-me"  # noqa: S105
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7

    # --- 限流（进程内滑动窗口，P0 只留配置位）---
    rate_limit_per_minute: int = 30

    # --- Agent 预算（P2/P3 使用，先固化口径）---
    max_tool_steps: int = 4
    llm_timeout_seconds: float = 30.0
    tool_timeout_seconds: float = 8.0
    prompt_token_budget: int = 6000
    session_lock_wait_seconds: float = 3.0
    history_window_turns: int = 10
    intent_confidence_threshold: float = 0.60
    # 输入守卫：超过该长度直接拦截，避免把整篇文档当提问塞进 prompt
    guard_max_input_chars: int = 600
    # 同一会话连续低置信达到该次数，主动建议转人工（计划 4.2）
    low_confidence_limit: int = 2
    # 工具候选商品保留数量：多轮指代（"第二个多少钱"）靠它定位
    candidate_keep: int = 5

    # --- LLM / Embedding（P1/P2 使用）---
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_api_key: str = ""
    llm_model: str = "deepseek-chat"
    llm_temperature: float = 0.3
    llm_max_tokens: int = 700
    llm_max_retries: int = 2
    # 意图理解用短输出即可，限制长度能明显压低首 token 前的等待
    understand_max_tokens: int = 400
    embedding_base_url: str = "https://api.siliconflow.cn/v1"
    embedding_api_key: str = ""
    embedding_model: str = "BAAI/bge-m3"
    embedding_dim: int = 1024
    embedding_batch_size: int = 16
    embedding_concurrency: int = 4
    embedding_timeout_seconds: float = 20.0
    embedding_max_retries: int = 3

    # --- RAG 检索（P1 纯向量，P3 加混合检索）---
    rag_chunk_size: int = 320
    rag_chunk_overlap: int = 70
    rag_top_k: int = 5
    # 余弦距离阈值：超过该值视为不相关，宁可答"没查到"也不硬凑引用（计划 4.3）
    rag_max_distance: float = 0.45


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

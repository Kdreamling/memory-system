"""
配置管理 - Reverie Gateway
"""

from functools import lru_cache
from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # Supabase
    supabase_url: str = ""
    supabase_key: str = ""
    supabase_db_url: str = ""

    # DeepSeek（主聊天 + 微摘要）
    llm_api_key: str = ""
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_model: str = "deepseek-chat"

    # OpenRouter
    openrouter_api_key: Optional[str] = ""

    # 硅基流动（Embedding + Rerank）
    siliconflow_api_key: Optional[str] = ""

    # DZZI 中转（Claude API）
    dzzi_api_key: Optional[str] = ""
    dzzi_per_use_api_key: Optional[str] = ""

    # 高德地图
    amap_api_key: str = ""

    # 搜索引擎
    serper_api_key: Optional[str] = ""

    # 代理
    proxy_url: str = ""
    yuque_token: str = ""

    # 服务
    gateway_port: int = 8001
    memu_port: int = 8000
    memu_url: str = "http://localhost:8000"

    # JWT鉴权
    auth_password: str = ""
    jwt_secret: str = ""
    jwt_expire_days: int = 7

    # 环境标识
    env: str = "dev"             # dev / prod

    class Config:
        env_file = "/home/dream/memory-system/.env"
        env_file_encoding = "utf-8"
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    return Settings()


# 功能降级开关 — 任一模块出问题时单独关闭，Gateway降级为纯代理
FEATURE_FLAGS = {
    "memory_enabled": True,
    "micro_summary_enabled": True,
    "search_enabled": True,
    "context_inject_enabled": True,
}


# 便捷函数
def get_supabase_config():
    s = get_settings()
    return {"url": s.supabase_url, "key": s.supabase_key}


def get_llm_config():
    s = get_settings()
    return {
        "api_key": s.llm_api_key,
        "base_url": s.llm_base_url,
        "model": s.llm_model,
    }


# ---- 共享 Supabase 客户端 ----

_supabase_client = None


def get_supabase():
    """全局共享的 Supabase 客户端"""
    global _supabase_client
    if _supabase_client is None:
        s = get_settings()
        from supabase import create_client
        _supabase_client = create_client(s.supabase_url, s.supabase_key)
    return _supabase_client

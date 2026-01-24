"""
配置管理 - 支持多后端API
"""

from functools import lru_cache
from pydantic_settings import BaseSettings
from typing import Optional
import os

class Settings(BaseSettings):
    # Supabase配置
    supabase_url: str = ""
    supabase_key: str = ""
    supabase_db_url: str = ""
    
    # DeepSeek配置（主要聊天API）
    llm_api_key: str = ""
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_model: str = "deepseek-chat"
    
    # OpenRouter配置（用于GPT-4o、Claude等）
    openrouter_api_key: Optional[str] = ""
    
    # 硅基流动配置（用于Embedding）
    siliconflow_api_key: Optional[str] = ""
    
    # 代理配置
    proxy_url: str = ""
    # 服务配置
    gateway_port: int = 8001
    memu_port: int = 8000
    memu_url: str = "http://localhost:8000"
    
    class Config:
        env_file = "/home/dream/memory-system/.env"
        env_file_encoding = "utf-8"
        extra = "ignore"

@lru_cache()
def get_settings() -> Settings:
    return Settings()

# 便捷函数
def get_supabase_config():
    s = get_settings()
    return {
        "url": s.supabase_url,
        "key": s.supabase_key
    }

def get_llm_config():
    s = get_settings()
    return {
        "api_key": s.llm_api_key,
        "base_url": s.llm_base_url,
        "model": s.llm_model
    }

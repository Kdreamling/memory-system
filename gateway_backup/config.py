from pydantic_settings import BaseSettings
from functools import lru_cache
class Settings(BaseSettings):
    # Supabase
    supabase_url: str
    supabase_key: str
    supabase_db_url: str
    
    # LLM (DeepSeek)
    llm_api_key: str
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_model: str = "deepseek-chat"
    
    # OpenAI (for embeddings)
    openai_api_key: str
    openai_base_url: str = "https://api.openai.com/v1"
    
    # Service
    gateway_port: int = 8001
    memu_port: int = 8000
    
    class Config:
        env_file = "/home/dream/memory-system/.env"

@lru_cache()
def get_settings():
    return Settings()

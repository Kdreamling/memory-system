from supabase import create_client
from datetime import datetime
from typing import Optional
import sys
sys.path.insert(0, '/home/dream/memory-system/gateway')
from config import get_settings

settings = get_settings()
supabase = create_client(settings.supabase_url, settings.supabase_key)

# 过滤关键词
SKIP_KEYWORDS = [
    "<content>",
    "summarize",
    "summary",
    "总结",
    "标题", 
    "title",
    "I will give you",
    "system_auto",
    "health_check",
    "你是一个",
    "You are a",
    "As an AI",
    "作为AI",
    "我是DeepSeek",
    "I am DeepSeek",
]

async def save_conversation(user_msg: str, assistant_msg: str, user_id: str = "dream") -> Optional[str]:
    """保存对话到数据库"""
    # 过滤系统请求
    for kw in SKIP_KEYWORDS:
        if kw.lower() in user_msg.lower():
            print(f"[skip] 系统消息: {user_msg[:50]}")
            return None
        if kw.lower() in assistant_msg.lower():
            print(f"[skip] 系统回复: {assistant_msg[:50]}")
            return None
    
    # 过滤太短的消息
    if len(user_msg.strip()) < 2 or len(assistant_msg.strip()) < 2:
        return None
    
    try:
        result = supabase.table("conversations").insert({
            "user_id": user_id,
            "user_msg": user_msg,
            "assistant_msg": assistant_msg,
            "synced_to_memu": False
        }).execute()
        
        if result.data:
            print(f"[saved] {user_msg[:30]}... -> {assistant_msg[:30]}...")
            return result.data[0]["id"]
        return None
    except Exception as e:
        print(f"[error] save: {e}")
        return None

async def get_recent_conversations(user_id: str = "dream", limit: int = 4) -> list:
    """获取最近的对话"""
    try:
        result = supabase.table("conversations") \
            .select("user_msg, assistant_msg, created_at") \
            .eq("user_id", user_id) \
            .order("created_at", desc=True) \
            .limit(limit) \
            .execute()
        return result.data if result.data else []
    except Exception as e:
        print(f"[error] get_recent: {e}")
        return []

async def get_unsynced_conversations(limit: int = 100) -> list:
    """获取未同步到MemU的对话"""
    try:
        result = supabase.table("conversations") \
            .select("*") \
            .eq("synced_to_memu", False) \
            .order("created_at", desc=False) \
            .limit(limit) \
            .execute()
        return result.data if result.data else []
    except Exception as e:
        print(f"[error] get_unsynced: {e}")
        return []

async def mark_synced(conversation_id: str) -> bool:
    """标记对话已同步"""
    try:
        supabase.table("conversations") \
            .update({"synced_to_memu": True}) \
            .eq("id", conversation_id) \
            .execute()
        return True
    except Exception as e:
        print(f"[error] mark_synced: {e}")
        return False

"""
Supabase 存储服务
"""

from supabase import create_client
from datetime import datetime
from typing import Optional, List, Dict
import sys

sys.path.insert(0, '/home/dream/memory-system/gateway')
from config import get_settings

settings = get_settings()
supabase = create_client(settings.supabase_url, settings.supabase_key)

# 过滤关键词
SKIP_KEYWORDS = [
    "<content>", "summarize", "summary", "总结", "标题", "title",
    "I will give you", "system_auto", "health_check",
    "你是一个", "You are a", "As an AI", "作为AI",
    "Generate a concise", "Based on the conversation"
]

async def save_conversation(
    user_msg: str, 
    assistant_msg: str, 
    user_id: str = "dream"
) -> Optional[str]:
    """保存对话到数据库"""
    
    # 过滤系统消息
    for kw in SKIP_KEYWORDS:
        if kw.lower() in user_msg.lower():
            print(f"[Storage] Skipped system message: {user_msg[:50]}...")
            return None
    
    # 过滤空消息
    if not user_msg.strip() or not assistant_msg.strip():
        return None
    
    try:
        result = supabase.table("conversations").insert({
            "user_id": user_id,
            "user_msg": user_msg,
            "assistant_msg": assistant_msg,
            "synced_to_memu": False
        }).execute()
        
        if result.data:
            conv_id = result.data[0]["id"]
            print(f"[Storage] Saved conversation {conv_id[:8]}...")
            return conv_id
        return None
        
    except Exception as e:
        print(f"[Storage] Error: {e}")
        return None


async def get_recent_conversations(
    user_id: str = "dream", 
    limit: int = 4
) -> List[Dict]:
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
        print(f"[Storage] Get recent error: {e}")
        return []


async def get_unsynced_conversations(limit: int = 100) -> List[Dict]:
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
        print(f"[Storage] Get unsynced error: {e}")
        return []


async def mark_synced(conversation_id: str) -> bool:
    """标记对话已同步到MemU"""
    try:
        supabase.table("conversations") \
            .update({"synced_to_memu": True}) \
            .eq("id", conversation_id) \
            .execute()
        return True
        
    except Exception as e:
        print(f"[Storage] Mark synced error: {e}")
        return False


async def search_conversations(
    query: str, 
    user_id: str = "dream", 
    limit: int = 5
) -> List[Dict]:
    """简单关键词搜索（MemU未就绪时的fallback）"""
    try:
        # 使用ilike进行模糊搜索
        result = supabase.table("conversations") \
            .select("user_msg, assistant_msg, created_at") \
            .eq("user_id", user_id) \
            .or_(f"user_msg.ilike.%{query}%,assistant_msg.ilike.%{query}%") \
            .order("created_at", desc=True) \
            .limit(limit) \
            .execute()
        
        return result.data if result.data else []
        
    except Exception as e:
        print(f"[Storage] Search error: {e}")
        return []

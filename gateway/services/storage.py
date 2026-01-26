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
async def update_weight(conversation_id: str, increment: int = 1) -> bool:
    """增加记忆权重（被AI引用时调用）"""
    try:
        # 先获取当前权重
        result = supabase.table("conversations") \
            .select("weight") \
            .eq("id", conversation_id) \
            .execute()
        
        if result.data:
            current = result.data[0].get("weight", 0) or 0
            new_weight = current + increment
            
            supabase.table("conversations") \
                .update({"weight": new_weight}) \
                .eq("id", conversation_id) \
                .execute()
            
            print(f"[Storage] Weight updated: {conversation_id[:8]}... -> {new_weight}")
            return True
        return False
        
    except Exception as e:
        print(f"[Storage] Update weight error: {e}")
        return False


async def get_by_id(conversation_id: str) -> Optional[Dict]:
    """根据ID获取对话"""
    try:
        result = supabase.table("conversations") \
            .select("*") \
            .eq("id", conversation_id) \
            .execute()
        
        return result.data[0] if result.data else None
        
    except Exception as e:
        print(f"[Storage] Get by id error: {e}")
        return None



# ============ Summary 相关函数 ============

async def get_current_round(user_id: str = "dream") -> int:
    """获取当前对话轮数"""
    try:
        result = supabase.table("conversations") \
            .select("round_number") \
            .eq("user_id", user_id) \
            .order("created_at", desc=True) \
            .limit(1) \
            .execute()
        
        if result.data and result.data[0].get("round_number"):
            return result.data[0]["round_number"]
        return 0
    except Exception as e:
        print(f"[Storage] Get round error: {e}")
        return 0


async def save_conversation_with_round(
    user_msg: str, 
    assistant_msg: str, 
    user_id: str = "dream"
) -> Optional[str]:
    """保存对话并记录轮数"""
    
    # 过滤系统消息
    for kw in SKIP_KEYWORDS:
        if kw.lower() in user_msg.lower():
            print(f"[Storage] Skipped system message: {user_msg[:50]}...")
            return None
    
    if not user_msg.strip() or not assistant_msg.strip():
        return None
    
    try:
        # 获取当前轮数+1
        current_round = await get_current_round(user_id)
        new_round = current_round + 1
        
        result = supabase.table("conversations").insert({
            "user_id": user_id,
            "user_msg": user_msg,
            "assistant_msg": assistant_msg,
            "synced_to_memu": False,
            "round_number": new_round
        }).execute()
        
        if result.data:
            conv_id = result.data[0]["id"]
            print(f"[Storage] Saved conversation {conv_id[:8]}... (round {new_round})")
            return conv_id
        return None
        
    except Exception as e:
        print(f"[Storage] Error: {e}")
        return None


async def get_conversations_for_summary(
    user_id: str = "dream",
    start_round: int = 1,
    end_round: int = 5
) -> List[Dict]:
    """获取指定轮数范围的对话，用于生成摘要"""
    try:
        result = supabase.table("conversations") \
            .select("user_msg, assistant_msg, round_number, created_at") \
            .eq("user_id", user_id) \
            .gte("round_number", start_round) \
            .lte("round_number", end_round) \
            .order("round_number", desc=False) \
            .execute()
        
        return result.data if result.data else []
    except Exception as e:
        print(f"[Storage] Get conversations for summary error: {e}")
        return []


async def save_summary(
    summary: str,
    start_round: int,
    end_round: int,
    user_id: str = "dream"
) -> Optional[str]:
    """保存摘要"""
    try:
        result = supabase.table("summaries").insert({
            "user_id": user_id,
            "summary": summary,
            "start_round": start_round,
            "end_round": end_round
        }).execute()
        
        if result.data:
            summary_id = result.data[0]["id"]
            print(f"[Storage] Saved summary {summary_id[:8]}... (rounds {start_round}-{end_round})")
            return summary_id
        return None
    except Exception as e:
        print(f"[Storage] Save summary error: {e}")
        return None


async def get_recent_summaries(
    user_id: str = "dream",
    limit: int = 3
) -> List[Dict]:
    """获取最近的摘要"""
    try:
        result = supabase.table("summaries") \
            .select("summary, start_round, end_round, created_at") \
            .eq("user_id", user_id) \
            .order("created_at", desc=True) \
            .limit(limit) \
            .execute()
        
        return result.data if result.data else []
    except Exception as e:
        print(f"[Storage] Get summaries error: {e}")
        return []


async def get_last_summarized_round(user_id: str = "dream") -> int:
    """获取最后一次摘要覆盖到的轮数"""
    try:
        result = supabase.table("summaries") \
            .select("end_round") \
            .eq("user_id", user_id) \
            .order("created_at", desc=True) \
            .limit(1) \
            .execute()
        
        if result.data:
            return result.data[0]["end_round"]
        return 0
    except Exception as e:
        print(f"[Storage] Get last summarized round error: {e}")
        return 0

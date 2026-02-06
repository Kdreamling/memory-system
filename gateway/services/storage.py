"""
Supabase 存储服务
修复：用 asyncio.to_thread() 包装同步调用，避免阻塞事件循环
"""

from supabase import create_client
from datetime import datetime
from typing import Optional, List, Dict
import asyncio
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


# ============ 核心改动：同步操作包装 ============
# supabase-py 是同步库，直接在 async 函数里调用会阻塞事件循环
# 用 asyncio.to_thread() 把它丢到线程池，事件循环就不会被卡住了

def _db_insert_conversation(user_id: str, user_msg: str, assistant_msg: str, round_number: int = None) -> Optional[dict]:
    """【同步】插入对话记录"""
    data = {
        "user_id": user_id,
        "user_msg": user_msg,
        "assistant_msg": assistant_msg,
        "synced_to_memu": False
    }
    if round_number is not None:
        data["round_number"] = round_number
    result = supabase.table("conversations").insert(data).execute()
    return result.data[0] if result.data else None


def _db_get_recent(user_id: str, limit: int) -> List[Dict]:
    """【同步】获取最近对话"""
    result = supabase.table("conversations") \
        .select("user_msg, assistant_msg, created_at") \
        .eq("user_id", user_id) \
        .order("created_at", desc=True) \
        .limit(limit) \
        .execute()
    return result.data if result.data else []


def _db_get_unsynced(limit: int) -> List[Dict]:
    """【同步】获取未同步对话"""
    result = supabase.table("conversations") \
        .select("*") \
        .eq("synced_to_memu", False) \
        .order("created_at", desc=False) \
        .limit(limit) \
        .execute()
    return result.data if result.data else []


def _db_mark_synced(conversation_id: str) -> bool:
    """【同步】标记已同步"""
    supabase.table("conversations") \
        .update({"synced_to_memu": True}) \
        .eq("id", conversation_id) \
        .execute()
    return True


def _db_search(query: str, user_id: str, limit: int) -> List[Dict]:
    """【同步】关键词搜索"""
    result = supabase.table("conversations") \
        .select("user_msg, assistant_msg, created_at") \
        .eq("user_id", user_id) \
        .or_(f"user_msg.ilike.%{query}%,assistant_msg.ilike.%{query}%") \
        .order("created_at", desc=True) \
        .limit(limit) \
        .execute()
    return result.data if result.data else []


def _db_update_weight(conversation_id: str, increment: int) -> bool:
    """【同步】更新权重 - 使用RPC避免竞争条件（如果有的话），否则先读后写"""
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
        return True
    return False


def _db_get_by_id(conversation_id: str) -> Optional[Dict]:
    """【同步】按ID查询"""
    result = supabase.table("conversations") \
        .select("*") \
        .eq("id", conversation_id) \
        .execute()
    return result.data[0] if result.data else None


def _db_get_current_round(user_id: str) -> int:
    """【同步】获取当前轮数"""
    result = supabase.table("conversations") \
        .select("round_number") \
        .eq("user_id", user_id) \
        .order("created_at", desc=True) \
        .limit(1) \
        .execute()
    if result.data and result.data[0].get("round_number"):
        return result.data[0]["round_number"]
    return 0


def _db_get_conversations_for_summary(user_id: str, start_round: int, end_round: int) -> List[Dict]:
    """【同步】获取指定轮数范围的对话"""
    result = supabase.table("conversations") \
        .select("user_msg, assistant_msg, round_number, created_at") \
        .eq("user_id", user_id) \
        .gte("round_number", start_round) \
        .lte("round_number", end_round) \
        .order("round_number", desc=False) \
        .execute()
    return result.data if result.data else []


def _db_save_summary(user_id: str, summary: str, start_round: int, end_round: int) -> Optional[dict]:
    """【同步】保存摘要"""
    result = supabase.table("summaries").insert({
        "user_id": user_id,
        "summary": summary,
        "start_round": start_round,
        "end_round": end_round
    }).execute()
    return result.data[0] if result.data else None


def _db_get_recent_summaries(user_id: str, limit: int) -> List[Dict]:
    """【同步】获取最近摘要"""
    result = supabase.table("summaries") \
        .select("summary, start_round, end_round, created_at") \
        .eq("user_id", user_id) \
        .order("created_at", desc=True) \
        .limit(limit) \
        .execute()
    return result.data if result.data else []


def _db_get_last_summarized_round(user_id: str) -> int:
    """【同步】获取最后摘要覆盖到的轮数"""
    result = supabase.table("summaries") \
        .select("end_round") \
        .eq("user_id", user_id) \
        .order("created_at", desc=True) \
        .limit(1) \
        .execute()
    if result.data:
        return result.data[0]["end_round"]
    return 0


# ============ 对外暴露的 async 接口（保持原有函数签名不变） ============

async def save_conversation(user_msg: str, assistant_msg: str, user_id: str = "dream") -> Optional[str]:
    """保存对话到数据库"""
    for kw in SKIP_KEYWORDS:
        if kw.lower() in user_msg.lower():
            print(f"[Storage] Skipped system message: {user_msg[:50]}...")
            return None
    if not user_msg.strip() or not assistant_msg.strip():
        return None
    try:
        row = await asyncio.to_thread(_db_insert_conversation, user_id, user_msg, assistant_msg)
        if row:
            conv_id = row["id"]
            print(f"[Storage] Saved conversation {conv_id[:8]}...")
            return conv_id
        return None
    except Exception as e:
        print(f"[Storage] Error: {e}")
        return None


async def get_recent_conversations(user_id: str = "dream", limit: int = 4) -> List[Dict]:
    """获取最近的对话"""
    try:
        return await asyncio.to_thread(_db_get_recent, user_id, limit)
    except Exception as e:
        print(f"[Storage] Get recent error: {e}")
        return []


async def get_unsynced_conversations(limit: int = 100) -> List[Dict]:
    """获取未同步到MemU的对话"""
    try:
        return await asyncio.to_thread(_db_get_unsynced, limit)
    except Exception as e:
        print(f"[Storage] Get unsynced error: {e}")
        return []


async def mark_synced(conversation_id: str) -> bool:
    """标记对话已同步到MemU"""
    try:
        return await asyncio.to_thread(_db_mark_synced, conversation_id)
    except Exception as e:
        print(f"[Storage] Mark synced error: {e}")
        return False


async def search_conversations(query: str, user_id: str = "dream", limit: int = 5) -> List[Dict]:
    """关键词搜索"""
    try:
        return await asyncio.to_thread(_db_search, query, user_id, limit)
    except Exception as e:
        print(f"[Storage] Search error: {e}")
        return []


async def update_weight(conversation_id: str, increment: int = 1) -> bool:
    """增加记忆权重"""
    try:
        result = await asyncio.to_thread(_db_update_weight, conversation_id, increment)
        if result:
            print(f"[Storage] Weight updated: {conversation_id[:8]}...")
        return result
    except Exception as e:
        print(f"[Storage] Update weight error: {e}")
        return False


async def get_by_id(conversation_id: str) -> Optional[Dict]:
    """根据ID获取对话"""
    try:
        return await asyncio.to_thread(_db_get_by_id, conversation_id)
    except Exception as e:
        print(f"[Storage] Get by id error: {e}")
        return None


async def get_current_round(user_id: str = "dream") -> int:
    """获取当前对话轮数"""
    try:
        return await asyncio.to_thread(_db_get_current_round, user_id)
    except Exception as e:
        print(f"[Storage] Get round error: {e}")
        return 0


async def save_conversation_with_round(user_msg: str, assistant_msg: str, user_id: str = "dream") -> Optional[str]:
    """保存对话并记录轮数"""
    for kw in SKIP_KEYWORDS:
        if kw.lower() in user_msg.lower():
            print(f"[Storage] Skipped system message: {user_msg[:50]}...")
            return None
    if not user_msg.strip() or not assistant_msg.strip():
        return None
    try:
        current_round = await asyncio.to_thread(_db_get_current_round, user_id)
        new_round = current_round + 1
        row = await asyncio.to_thread(_db_insert_conversation, user_id, user_msg, assistant_msg, new_round)
        if row:
            conv_id = row["id"]
            print(f"[Storage] Saved conversation {conv_id[:8]}... (round {new_round})")
            return conv_id
        return None
    except Exception as e:
        print(f"[Storage] Error: {e}")
        return None


async def get_conversations_for_summary(user_id: str = "dream", start_round: int = 1, end_round: int = 5) -> List[Dict]:
    """获取指定轮数范围的对话"""
    try:
        return await asyncio.to_thread(_db_get_conversations_for_summary, user_id, start_round, end_round)
    except Exception as e:
        print(f"[Storage] Get conversations for summary error: {e}")
        return []


async def save_summary(summary: str, start_round: int, end_round: int, user_id: str = "dream") -> Optional[str]:
    """保存摘要"""
    try:
        row = await asyncio.to_thread(_db_save_summary, user_id, summary, start_round, end_round)
        if row:
            summary_id = row["id"]
            print(f"[Storage] Saved summary {summary_id[:8]}... (rounds {start_round}-{end_round})")
            return summary_id
        return None
    except Exception as e:
        print(f"[Storage] Save summary error: {e}")
        return None


async def get_recent_summaries(user_id: str = "dream", limit: int = 3) -> List[Dict]:
    """获取最近的摘要"""
    try:
        return await asyncio.to_thread(_db_get_recent_summaries, user_id, limit)
    except Exception as e:
        print(f"[Storage] Get summaries error: {e}")
        return []


async def get_last_summarized_round(user_id: str = "dream") -> int:
    """获取最后一次摘要覆盖到的轮数"""
    try:
        return await asyncio.to_thread(_db_get_last_summarized_round, user_id)
    except Exception as e:
        print(f"[Storage] Get last summarized round error: {e}")
        return 0

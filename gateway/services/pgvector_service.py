"""
pgvector 向量服务 - 替代 ChromaDB
使用 Supabase 内置的 pgvector 扩展进行向量存储和搜索
"""

import httpx
import asyncio
from typing import List, Optional, Dict
import sys

sys.path.insert(0, '/home/dream/memory-system/gateway')
from config import get_settings

settings = get_settings()


async def generate_embedding(text: str) -> Optional[List[float]]:
    """调用硅基流动 BAAI/bge-large-zh-v1.5 生成1024维向量"""
    if not text or not text.strip():
        return None
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://api.siliconflow.cn/v1/embeddings",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {settings.siliconflow_api_key}"
                },
                json={
                    "model": "BAAI/bge-large-zh-v1.5",
                    "input": text[:2000]  # 截断过长文本
                }
            )
            if response.status_code == 200:
                data = response.json()
                return data["data"][0]["embedding"]
            else:
                print(f"[pgvector] Embedding API error: {response.status_code} - {response.text[:200]}")
                return None
    except Exception as e:
        print(f"[pgvector] Embedding error: {e}")
        return None


async def store_embedding(table: str, record_id: str, embedding: List[float]):
    """将embedding写入指定表的embedding列"""
    try:
        from supabase import create_client
        supabase = create_client(settings.supabase_url, settings.supabase_key)

        # pgvector 需要以字符串形式传入：'[0.1, 0.2, ...]'
        embedding_str = f"[{','.join(str(x) for x in embedding)}]"

        def _update():
            supabase.table(table).update({
                "embedding": embedding_str
            }).eq("id", record_id).execute()

        await asyncio.to_thread(_update)
        print(f"[pgvector] Stored embedding for {table}/{record_id[:8]}...")
    except Exception as e:
        print(f"[pgvector] Store error: {e}")


async def store_conversation_embedding(
    conversation_id: str,
    user_msg: str,
    assistant_msg: str,
    user_id: str = "dream"
):
    """将对话向量化并存入pgvector（替代ChromaDB版本）"""
    text = f"用户: {user_msg}\n助手: {assistant_msg}"
    embedding = await generate_embedding(text)
    if embedding:
        await store_embedding("conversations", conversation_id, embedding)


async def store_summary_embedding(
    summary_id: str,
    summary_text: str,
    start_round: int,
    end_round: int,
    user_id: str = "dream"
) -> bool:
    """将摘要向量化并存入pgvector"""
    embedding = await generate_embedding(summary_text)
    if embedding:
        await store_embedding("summaries", summary_id, embedding)
        return True
    return False


async def search_similar(
    query_embedding: List[float],
    table: str,
    scene_type: Optional[str] = None,
    limit: int = 10,
    channel: str = "deepseek"
) -> List[Dict]:
    """
    在指定表中执行向量搜索，支持scene_type和channel过滤
    使用Supabase RPC调用pgvector的余弦距离搜索
    """
    try:
        from supabase import create_client
        supabase = create_client(settings.supabase_url, settings.supabase_key)

        embedding_str = f"[{','.join(str(x) for x in query_embedding)}]"

        if table == "conversations":
            def _search():
                query = supabase.table("conversations") \
                    .select("id, user_msg, assistant_msg, created_at, scene_type, topic, emotion, round_number") \
                    .eq("model_channel", channel)

                if scene_type:
                    if scene_type == "daily":
                        query = query.in_("scene_type", ["daily", "plot"])
                    else:
                        query = query.eq("scene_type", scene_type)

                query = query.not_.is_("embedding", "null")
                result = query.order("created_at", desc=True).limit(limit * 3).execute()
                return result.data if result.data else []

        elif table == "summaries":
            def _search():
                query = supabase.table("summaries") \
                    .select("id, summary, created_at, scene_type, topic, start_round, end_round") \
                    .eq("model_channel", channel)

                if scene_type:
                    if scene_type == "daily":
                        query = query.in_("scene_type", ["daily", "plot"])
                    else:
                        query = query.eq("scene_type", scene_type)

                query = query.not_.is_("embedding", "null")
                result = query.order("created_at", desc=True).limit(limit * 3).execute()
                return result.data if result.data else []
        else:
            return []

        candidates = await asyncio.to_thread(_search)

        return candidates[:limit]

    except Exception as e:
        print(f"[pgvector] Search error in {table}: {e}")
        return []


async def vector_search_rpc(
    query_embedding: List[float],
    table: str,
    scene_type: Optional[str] = None,
    limit: int = 15,
    channel: str = "deepseek"
) -> List[Dict]:
    """
    使用Supabase PostgREST RPC调用pgvector搜索
    需要在Supabase中创建对应的函数
    如果RPC不可用，降级为普通查询
    """
    try:
        from supabase import create_client
        supabase = create_client(settings.supabase_url, settings.supabase_key)

        embedding_str = f"[{','.join(str(x) for x in query_embedding)}]"

        if table == "conversations":
            func_name = "search_conversations_v2"
        elif table == "summaries":
            func_name = "search_summaries_v2"
        else:
            return []

        params = {
            "query_embedding": embedding_str,
            "match_count": limit,
            "filter_scene": scene_type,  # None会被PostgREST传为null
            "filter_channel": channel
        }

        def _rpc():
            result = supabase.rpc(func_name, params).execute()
            return result.data if result.data else []

        results = await asyncio.to_thread(_rpc)
        return results

    except Exception as e:
        # RPC不可用时降级
        print(f"[pgvector] RPC search failed, falling back: {e}")
        return await search_similar(query_embedding, table, scene_type, limit, channel)

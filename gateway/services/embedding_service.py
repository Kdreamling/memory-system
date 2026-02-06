"""
Embedding 服务 - ChromaDB 向量搜索
修复：用 asyncio.to_thread() 包装同步调用，避免阻塞事件循环
"""

import httpx
import chromadb
from chromadb.config import Settings
from datetime import datetime, timedelta
from typing import List, Optional
import asyncio
import sys
import os

sys.path.insert(0, '/home/dream/memory-system/gateway')
from config import get_settings

settings = get_settings()

# ChromaDB 本地持久化
chroma_client = chromadb.PersistentClient(path="/home/dream/memory-system/chroma_db")
collection = chroma_client.get_or_create_collection(
    name="conversations",
    metadata={"hnsw:space": "cosine"}
)

# 摘要专用collection（永久保留）
summary_collection = chroma_client.get_or_create_collection(
    name="summaries",
    metadata={"hnsw:space": "cosine"}
)


# ============ Embedding API（本身就是async的，不需要改） ============

async def get_embedding(text: str) -> Optional[List[float]]:
    """调用硅基流动API获取embedding"""
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
                    "input": text
                }
            )
            if response.status_code == 200:
                data = response.json()
                return data["data"][0]["embedding"]
            else:
                print(f"Embedding API error: {response.status_code}")
                return None
    except Exception as e:
        print(f"Embedding error: {e}")
        return None


# ============ ChromaDB 同步操作（下层） ============

def _chroma_add(col, ids, embeddings, documents, metadatas):
    """【同步】向 collection 添加数据"""
    col.add(ids=ids, embeddings=embeddings, documents=documents, metadatas=metadatas)


def _chroma_query(col, query_embeddings, n_results, where=None):
    """【同步】查询 collection"""
    kwargs = {"query_embeddings": query_embeddings, "n_results": n_results}
    if where:
        kwargs["where"] = where
    return col.query(**kwargs)


def _chroma_get_all(col):
    """【同步】获取 collection 所有数据（用于清理）"""
    return col.get(include=["metadatas"])


def _chroma_delete(col, ids):
    """【同步】删除指定 ID"""
    col.delete(ids=ids)


# ============ 对外暴露的 async 接口（签名不变） ============

async def store_conversation_embedding(
    conversation_id: str,
    user_msg: str,
    assistant_msg: str,
    user_id: str = "dream"
):
    """将对话向量化并存入ChromaDB"""
    text = f"用户: {user_msg}\n助手: {assistant_msg}"

    embedding = await get_embedding(text)
    if not embedding:
        print(f"Failed to get embedding for {conversation_id}")
        return False

    try:
        await asyncio.to_thread(
            _chroma_add,
            collection,
            [conversation_id],
            [embedding],
            [text],
            [{
                "user_id": user_id,
                "user_msg": user_msg[:500],
                "assistant_msg": assistant_msg[:500],
                "created_at": datetime.now().isoformat()
            }]
        )
        print(f"Stored embedding: {conversation_id}")
        return True
    except Exception as e:
        print(f"ChromaDB store error: {e}")
        return False


async def search_similar(query: str, user_id: str = "dream", limit: int = 5) -> List[dict]:
    """语义搜索相似对话"""
    query_embedding = await get_embedding(query)
    if not query_embedding:
        return []

    try:
        results = await asyncio.to_thread(
            _chroma_query,
            collection,
            [query_embedding],
            limit,
            {"user_id": user_id}
        )

        conversations = []
        if results and results['documents']:
            for i, doc in enumerate(results['documents'][0]):
                meta = results['metadatas'][0][i] if results['metadatas'] else {}
                conversations.append({
                    "id": results['ids'][0][i],
                    "user_msg": meta.get("user_msg", ""),
                    "assistant_msg": meta.get("assistant_msg", ""),
                    "created_at": meta.get("created_at", ""),
                    "distance": results['distances'][0][i] if results.get('distances') else None
                })
        return conversations
    except Exception as e:
        print(f"Search error: {e}")
        return []


async def cleanup_old_embeddings(days: int = 7):
    """清理超过N天的向量（旧版占位，实际用 cleanup_old_embeddings_real）"""
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    print(f"Cleanup embeddings older than {cutoff}")


async def cleanup_old_embeddings_real(days: int = 7) -> int:
    """清理超过N天的对话向量"""
    cutoff = datetime.now() - timedelta(days=days)
    cutoff_str = cutoff.isoformat()

    try:
        all_data = await asyncio.to_thread(_chroma_get_all, collection)

        if not all_data or not all_data['ids']:
            print("[Cleanup] No data in ChromaDB")
            return 0

        expired_ids = []
        for i, meta in enumerate(all_data['metadatas']):
            created_at = meta.get("created_at", "")
            if created_at and created_at < cutoff_str:
                expired_ids.append(all_data['ids'][i])

        if expired_ids:
            await asyncio.to_thread(_chroma_delete, collection, expired_ids)
            print(f"[Cleanup] Deleted {len(expired_ids)} expired embeddings")
            return len(expired_ids)
        else:
            print("[Cleanup] No expired embeddings found")
            return 0

    except Exception as e:
        print(f"[Cleanup] Error: {e}")
        return 0


async def store_summary_embedding(
    summary_id: str,
    summary_text: str,
    start_round: int,
    end_round: int,
    user_id: str = "dream"
) -> bool:
    """将摘要向量化并存入ChromaDB（永久保留）"""
    embedding = await get_embedding(summary_text)
    if not embedding:
        print(f"[Summary Embedding] Failed for {summary_id}")
        return False

    try:
        await asyncio.to_thread(
            _chroma_add,
            summary_collection,
            [summary_id],
            [embedding],
            [summary_text],
            [{
                "user_id": user_id,
                "start_round": start_round,
                "end_round": end_round,
                "type": "summary",
                "created_at": datetime.now().isoformat()
            }]
        )
        print(f"[Summary Embedding] Stored: {summary_id}")
        return True
    except Exception as e:
        print(f"[Summary Embedding] Error: {e}")
        return False


async def search_summaries(query: str, user_id: str = "dream", limit: int = 3) -> List[dict]:
    """语义搜索摘要"""
    query_embedding = await get_embedding(query)
    if not query_embedding:
        return []

    try:
        results = await asyncio.to_thread(
            _chroma_query,
            summary_collection,
            [query_embedding],
            limit,
            {"user_id": user_id}
        )

        summaries = []
        if results and results['documents']:
            for i, doc in enumerate(results['documents'][0]):
                meta = results['metadatas'][0][i] if results['metadatas'] else {}
                summaries.append({
                    "id": results['ids'][0][i],
                    "summary": doc,
                    "start_round": meta.get("start_round"),
                    "end_round": meta.get("end_round"),
                    "created_at": meta.get("created_at", ""),
                    "distance": results['distances'][0][i] if results.get('distances') else None
                })
        return summaries
    except Exception as e:
        print(f"[Summary Search] Error: {e}")
        return []

import httpx
import chromadb
from chromadb.config import Settings
from datetime import datetime, timedelta
from typing import List, Optional
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

async def store_conversation_embedding(
    conversation_id: str,
    user_msg: str,
    assistant_msg: str,
    user_id: str = "dream"
):
    """将对话向量化并存入ChromaDB"""
    # 拼接对话文本
    text = f"用户: {user_msg}\n助手: {assistant_msg}"
    
    # 获取embedding
    embedding = await get_embedding(text)
    if not embedding:
        print(f"Failed to get embedding for {conversation_id}")
        return False
    
    # 存入ChromaDB
    try:
        collection.add(
            ids=[conversation_id],
            embeddings=[embedding],
            documents=[text],
            metadatas=[{
                "user_id": user_id,
                "user_msg": user_msg[:500],  # 截断防止过长
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
    # 获取查询的embedding
    query_embedding = await get_embedding(query)
    if not query_embedding:
        return []
    
    try:
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=limit,
            where={"user_id": user_id}
        )
        
        # 格式化结果
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
    """清理超过N天的向量（可选，定时调用）"""
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    try:
        # ChromaDB暂不支持按时间批量删除，需要先查询再删除
        # 这里简化处理，实际可用定时任务
        print(f"Cleanup embeddings older than {cutoff}")
        # TODO: 实现批量删除逻辑
    except Exception as e:
        print(f"Cleanup error: {e}")

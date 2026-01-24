"""
MemU 客户端 - 语义搜索服务
"""

import httpx
from typing import List, Dict, Optional
import sys

sys.path.insert(0, '/home/dream/memory-system/gateway')
from config import get_settings

settings = get_settings()
MEMU_URL = settings.memu_url  # 默认 http://localhost:8000

# MemU服务状态
_memu_available = None

async def check_memu_health() -> bool:
    """检查MemU服务是否可用"""
    global _memu_available
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{MEMU_URL}/")
            _memu_available = response.status_code == 200
            return _memu_available
    except:
        _memu_available = False
        return False


async def memorize(user_id: str, conversation: str) -> bool:
    """
    存储记忆到MemU
    
    Args:
        user_id: 用户ID
        conversation: 格式化的对话文本，如 "User: xxx\nAssistant: xxx"
    
    Returns:
        是否成功
    """
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{MEMU_URL}/memorize",
                json={
                    "user_id": user_id,
                    "conversation": conversation
                }
            )
            success = response.status_code == 200
            if success:
                print(f"[MemU] Memorized for user {user_id}")
            else:
                print(f"[MemU] Memorize failed: {response.status_code} - {response.text[:100]}")
            return success
            
    except httpx.ConnectError:
        print("[MemU] Connection failed - service may not be running")
        return False
    except Exception as e:
        print(f"[MemU] Memorize error: {e}")
        return False


async def retrieve(
    user_id: str, 
    query: str, 
    limit: int = 5
) -> List[Dict]:
    """
    从MemU检索相关记忆
    
    Args:
        user_id: 用户ID
        query: 搜索查询
        limit: 返回数量
    
    Returns:
        记忆列表
    """
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{MEMU_URL}/retrieve",
                json={
                    "user_id": user_id,
                    "query": query,
                    "limit": limit
                }
            )
            
            if response.status_code == 200:
                data = response.json()
                memories = data.get("memories", [])
                print(f"[MemU] Retrieved {len(memories)} memories for query: {query[:30]}...")
                return memories
            else:
                print(f"[MemU] Retrieve failed: {response.status_code}")
                return []
                
    except httpx.ConnectError:
        print("[MemU] Connection failed - falling back to keyword search")
        return []
    except Exception as e:
        print(f"[MemU] Retrieve error: {e}")
        return []


async def is_available() -> bool:
    """检查MemU是否可用"""
    global _memu_available
    if _memu_available is None:
        await check_memu_health()
    return _memu_available or False

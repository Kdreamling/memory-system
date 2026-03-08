"""
搜索引擎集成 — Serper.dev
Phase 1 用 Serper（免费 2500 次/月），后续可切换
"""

import logging
from typing import Optional

import httpx

from config import get_settings

logger = logging.getLogger(__name__)

SEARCH_PROVIDERS = {
    "serper": {
        "url": "https://google.serper.dev/search",
        "parse": "_parse_serper",
    },
}

ACTIVE_PROVIDER = "serper"


async def web_search(query: str, num_results: int = 5) -> list:
    """执行网页搜索，返回格式化结果"""
    s = get_settings()
    api_key = s.serper_api_key

    if not api_key:
        logger.warning("[search] SERPER_API_KEY 未配置，跳过搜索")
        return []

    provider = SEARCH_PROVIDERS[ACTIVE_PROVIDER]

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                provider["url"],
                headers={
                    "X-API-KEY": api_key,
                    "Content-Type": "application/json",
                },
                json={
                    "q": query,
                    "num": num_results,
                    "gl": "cn",
                    "hl": "zh-cn",
                },
            )
            resp.raise_for_status()
            return _parse_serper(resp.json())

    except httpx.TimeoutException:
        logger.error("[search] 搜索超时")
        return []
    except Exception as e:
        logger.error(f"[search] 搜索异常: {e}")
        return []


def _parse_serper(data: dict) -> list:
    """解析 Serper 返回结果"""
    results = []

    # 常规搜索结果
    for item in data.get("organic", []):
        results.append({
            "title": item.get("title", ""),
            "url": item.get("link", ""),
            "snippet": item.get("snippet", ""),
            "source": "serper",
        })

    # 知识面板（如果有）
    kg = data.get("knowledgeGraph")
    if kg:
        results.insert(0, {
            "title": kg.get("title", ""),
            "url": kg.get("website", ""),
            "snippet": kg.get("description", ""),
            "source": "knowledge_graph",
        })

    return results
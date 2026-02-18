"""
混合检索服务
编排：关键词搜索 + 向量搜索 + 同义词扩展 + 合并去重 + rerank
"""

import httpx
import asyncio
from typing import List, Dict, Optional
from datetime import datetime, timedelta
import sys

sys.path.insert(0, '/home/dream/memory-system/gateway')
from config import get_settings
from services.pgvector_service import generate_embedding, vector_search_rpc

settings = get_settings()

# 检索总超时控制（秒）
SEARCH_TIMEOUT = 3.0


async def hybrid_search(
    query: str,
    scene_type: str = "daily",
    synonym_service=None,
    limit: int = 5
) -> List[Dict]:
    """
    执行混合检索

    参数：
        query: 用户查询
        scene_type: 当前场景类型
        synonym_service: 同义词服务实例
        limit: 最终返回条数

    返回：
        排序后的检索结果列表
    """
    if scene_type == "meta":
        return []

    try:
        results = await asyncio.wait_for(
            _do_hybrid_search(query, scene_type, synonym_service, limit),
            timeout=SEARCH_TIMEOUT
        )
        return results
    except asyncio.TimeoutError:
        print(f"[HybridSearch] Timeout after {SEARCH_TIMEOUT}s")
        return []
    except Exception as e:
        print(f"[HybridSearch] Error: {e}")
        return []


async def _do_hybrid_search(
    query: str,
    scene_type: str,
    synonym_service,
    limit: int
) -> List[Dict]:
    """执行实际的混合检索流程"""

    # 1. 同义词扩展
    expanded_terms = [query]
    if synonym_service:
        expanded_terms = synonym_service.expand(query)
        if query not in expanded_terms:
            expanded_terms.insert(0, query)
    print(f"[HybridSearch] Expanded terms: {expanded_terms[:10]}")

    # 2. 并行执行关键词搜索和向量搜索
    keyword_task = asyncio.create_task(
        _keyword_search(expanded_terms, scene_type, limit=15)
    )
    vector_task = asyncio.create_task(
        _vector_search(query, scene_type, limit=15)
    )

    keyword_results, vector_results = await asyncio.gather(
        keyword_task, vector_task, return_exceptions=True
    )

    # 处理异常情况
    if isinstance(keyword_results, Exception):
        print(f"[HybridSearch] Keyword search error: {keyword_results}")
        keyword_results = []
    if isinstance(vector_results, Exception):
        print(f"[HybridSearch] Vector search error: {vector_results}")
        vector_results = []

    # 3. 合并去重
    merged = _merge_and_dedupe(keyword_results, vector_results)
    print(f"[HybridSearch] Merged: {len(merged)} candidates (kw={len(keyword_results)}, vec={len(vector_results)})")

    if not merged:
        return []

    # 4. Rerank（或降级为简单排序）
    reranked = await _rerank(query, merged, limit)
    return reranked


async def _keyword_search(
    terms: List[str],
    scene_type: str,
    limit: int = 15
) -> List[Dict]:
    """关键词搜索：使用pg_trgm模糊匹配"""
    try:
        from supabase import create_client
        supabase = create_client(settings.supabase_url, settings.supabase_key)

        all_results = []

        def _search_term(term: str):
            """搜索单个关键词"""
            results = []

            # 搜索 conversations 表
            try:
                query = supabase.table("conversations") \
                    .select("id, user_msg, assistant_msg, created_at, scene_type, topic, emotion, round_number") \
                    .or_(f"user_msg.ilike.%{term}%,assistant_msg.ilike.%{term}%")

                if scene_type == "plot":
                    query = query.eq("scene_type", "plot")
                elif scene_type == "daily":
                    query = query.in_("scene_type", ["daily", "plot"])

                result = query.order("created_at", desc=True).limit(limit).execute()
                if result.data:
                    for row in result.data:
                        row["_source"] = "conversations"
                    results.extend(result.data)
            except Exception as e:
                print(f"[HybridSearch] Keyword conv search error: {e}")

            # 搜索 summaries 表
            try:
                query = supabase.table("summaries") \
                    .select("id, summary, created_at, scene_type, topic, start_round, end_round") \
                    .ilike("summary", f"%{term}%")

                if scene_type == "plot":
                    query = query.eq("scene_type", "plot")
                elif scene_type == "daily":
                    query = query.in_("scene_type", ["daily", "plot"])

                result = query.order("created_at", desc=True).limit(5).execute()
                if result.data:
                    for row in result.data:
                        row["_source"] = "summaries"
                    results.extend(result.data)
            except Exception as e:
                print(f"[HybridSearch] Keyword sum search error: {e}")

            return results

        # 限制搜索的关键词数量（避免过多请求）
        search_terms = terms[:5]
        for term in search_terms:
            if len(term) >= 2:  # 跳过太短的词
                term_results = await asyncio.to_thread(_search_term, term)
                all_results.extend(term_results)

        return all_results

    except Exception as e:
        print(f"[HybridSearch] Keyword search error: {e}")
        return []


async def _vector_search(
    query: str,
    scene_type: str,
    limit: int = 15
) -> List[Dict]:
    """向量搜索：使用pgvector"""
    try:
        query_embedding = await generate_embedding(query)
        if not query_embedding:
            return []

        # 搜索conversations和summaries
        conv_results = await vector_search_rpc(
            query_embedding, "conversations", scene_type, limit
        )
        sum_results = await vector_search_rpc(
            query_embedding, "summaries", scene_type, 5
        )

        for row in conv_results:
            row["_source"] = "conversations"
        for row in sum_results:
            row["_source"] = "summaries"

        return conv_results + sum_results

    except Exception as e:
        print(f"[HybridSearch] Vector search error: {e}")
        return []


def _merge_and_dedupe(
    keyword_results: List[Dict],
    vector_results: List[Dict]
) -> List[Dict]:
    """合并去重"""
    seen_ids = set()
    merged = []

    # 先加向量搜索结果（通常更相关）
    for item in vector_results:
        item_id = item.get("id", "")
        if item_id and item_id not in seen_ids:
            seen_ids.add(item_id)
            item["_match_type"] = "vector"
            merged.append(item)

    # 再加关键词搜索结果
    for item in keyword_results:
        item_id = item.get("id", "")
        if item_id and item_id not in seen_ids:
            seen_ids.add(item_id)
            item["_match_type"] = "keyword"
            merged.append(item)
        elif item_id in seen_ids:
            # 两种搜索都命中的，标记为 both（更可能相关）
            for m in merged:
                if m.get("id") == item_id:
                    m["_match_type"] = "both"
                    break

    return merged


async def _rerank(query: str, candidates: List[Dict], limit: int = 5) -> List[Dict]:
    """
    Rerank: 调用硅基流动rerank API
    失败时降级为简单排序
    """
    if len(candidates) <= limit:
        return candidates

    # 准备文档文本
    documents = []
    for item in candidates:
        if item.get("_source") == "summaries":
            text = item.get("summary", "")
        else:
            text = f"{item.get('user_msg', '')} {item.get('assistant_msg', '')}"
        documents.append(text[:500])  # 截断

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(
                "https://api.siliconflow.cn/v1/rerank",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {settings.siliconflow_api_key}"
                },
                json={
                    "model": "BAAI/bge-reranker-v2-m3",
                    "query": query,
                    "documents": documents,
                    "top_n": limit
                }
            )
            if response.status_code == 200:
                data = response.json()
                rerank_results = data.get("results", [])
                # 按rerank分数重新排列候选
                reranked = []
                for rr in rerank_results:
                    idx = rr.get("index", 0)
                    if idx < len(candidates):
                        item = candidates[idx]
                        item["_rerank_score"] = rr.get("relevance_score", 0)
                        reranked.append(item)
                print(f"[HybridSearch] Reranked: {len(reranked)} results")
                return reranked
            else:
                print(f"[HybridSearch] Rerank API error: {response.status_code}")
    except Exception as e:
        print(f"[HybridSearch] Rerank failed, falling back: {e}")

    # 降级：优先both > vector > keyword，然后按时间排序
    return _fallback_sort(candidates, limit)


def _fallback_sort(candidates: List[Dict], limit: int) -> List[Dict]:
    """降级排序：match_type优先，然后按时间"""
    priority = {"both": 0, "vector": 1, "keyword": 2}
    candidates.sort(key=lambda x: (
        priority.get(x.get("_match_type", "keyword"), 2),
        x.get("created_at", "") or ""
    ), reverse=False)
    # 时间需要倒序（最新的在前），但priority需要正序
    # 重新排序：先按priority，再按时间倒序
    candidates.sort(key=lambda x: (
        priority.get(x.get("_match_type", "keyword"), 2),
        -(datetime.fromisoformat(x["created_at"].replace("Z", "+00:00")).timestamp() if x.get("created_at") else 0)
    ))
    return candidates[:limit]


async def search_recent_by_emotion(
    emotion: str,
    days: int = 3,
    limit: int = 5
) -> List[Dict]:
    """搜索近期相同情感的对话"""
    try:
        from supabase import create_client
        supabase = create_client(settings.supabase_url, settings.supabase_key)

        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()

        def _search():
            result = supabase.table("conversations") \
                .select("id, user_msg, assistant_msg, created_at, scene_type, emotion") \
                .eq("emotion", emotion) \
                .gte("created_at", cutoff) \
                .order("created_at", desc=True) \
                .limit(limit) \
                .execute()
            return result.data if result.data else []

        return await asyncio.to_thread(_search)
    except Exception as e:
        print(f"[HybridSearch] Emotion search error: {e}")
        return []

"""
上下文构建器 — Reverie 的大脑层
负责在每次对话前组装注入给模型的上下文

优先级：核心记忆 > 全局滑动窗口 > 智能检索 > 中期摘要
硬性上限：2500 tokens
"""

import math
import asyncio
from datetime import datetime, timezone, timedelta

from config import get_settings, get_supabase


TOKEN_BUDGET = 2500


def count_tokens(text: str) -> int:
    """粗略估算 token 数（中文约1.5字/token，英文约4字符/token）"""
    if not text:
        return 0
    chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    other_chars = len(text) - chinese_chars
    return int(chinese_chars / 1.5 + other_chars / 4)


def truncate_to_budget(text: str, max_tokens: int) -> str:
    """按 token 预算截断文本"""
    if count_tokens(text) <= max_tokens:
        return text
    # 粗略按比例截断
    ratio = max_tokens / max(count_tokens(text), 1)
    cut_len = int(len(text) * ratio * 0.9)  # 留10%余量
    return text[:cut_len] + "\n..."


def format_with_time_gradient(memories: list) -> str:
    """按时间梯度控制展示粒度
    - 3天内：完整展示（最多4句）
    - 14天内：摘要展示（最多2句）
    - 更早：一句话概括
    """
    now = datetime.now(timezone.utc)
    formatted = []

    for m in memories:
        content = m.get("content") or m.get("user_msg", "")
        created = m.get("created_at", "")

        try:
            if isinstance(created, str):
                created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
            else:
                created_dt = created
            age_days = (now - created_dt).days
        except Exception:
            age_days = 999

        sentences = [s.strip() for s in content.replace("。", "。\n").split("\n") if s.strip()]

        if age_days <= 3:
            text = "。".join(sentences[:4])
        elif age_days <= 14:
            text = "。".join(sentences[:2])
        else:
            text = sentences[0] if sentences else content[:80]

        formatted.append(text)

    return "\n".join(formatted)


# ---- 记忆相关性评分 ----

def memory_relevance_score(memory: dict, rerank_score: float = 0.5) -> float:
    """core_base 不衰减，其他层按时间衰减 + 命中加成"""
    layer = memory.get("layer", "core_living")

    if layer == "core_base":
        importance = memory.get("base_importance", 0.5)
        return rerank_score * 0.7 + importance * 0.3

    # 衰减计算
    last_accessed = memory.get("last_accessed_at")
    try:
        if isinstance(last_accessed, str):
            last_dt = datetime.fromisoformat(last_accessed.replace("Z", "+00:00"))
        else:
            last_dt = last_accessed or datetime.now(timezone.utc)
        age_days = (datetime.now(timezone.utc) - last_dt).days
    except Exception:
        age_days = 30

    hits = memory.get("hits", 0)
    base_importance = memory.get("base_importance", 0.5)

    decay = math.exp(-0.03 * age_days)  # 半衰期约23天
    boost = 1 + math.log1p(hits) * 0.1
    importance = base_importance * decay * boost

    return rerank_score * 0.7 + importance * 0.3


async def on_memory_injected(memory_id: str):
    """每次注入记忆时更新访问记录"""
    try:
        sb = get_supabase()
        # 先拿当前 hits
        current = sb.table("memories").select("hits").eq("id", memory_id).execute()
        if current.data:
            new_hits = (current.data[0].get("hits") or 0) + 1
            sb.table("memories").update({
                "hits": new_hits,
                "last_accessed_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", memory_id).execute()
    except Exception as e:
        print(f"[context_builder] on_memory_injected error: {e}")


# ---- 数据获取函数 ----

async def fetch_core_memories(scene_type: str = "daily") -> tuple:
    """获取核心记忆（base + living + scene）"""
    sb = get_supabase()

    core_base = sb.table("memories") \
        .select("*") \
        .eq("layer", "core_base") \
        .order("base_importance", desc=True) \
        .execute()

    core_living = sb.table("memories") \
        .select("*") \
        .eq("layer", "core_living") \
        .order("last_accessed_at", desc=True) \
        .limit(10) \
        .execute()

    scene = sb.table("memories") \
        .select("*") \
        .eq("layer", "scene") \
        .eq("scene_type", scene_type) \
        .order("last_accessed_at", desc=True) \
        .limit(5) \
        .execute()

    return core_base.data or [], core_living.data or [], scene.data or []


async def fetch_global_recent(limit: int = 3) -> list:
    """跨 session 全局时间线最新 N 轮对话"""
    sb = get_supabase()
    result = sb.table("conversations") \
        .select("user_msg, assistant_msg, scene_type, created_at") \
        .order("created_at", desc=True) \
        .limit(limit * 2) \
        .execute()
    return result.data or []


async def fetch_merged_summaries(scene_type: str = None, days: int = 30) -> list:
    """获取中期摘要"""
    sb = get_supabase()
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    query = sb.table("memory_summaries") \
        .select("dimension, merged_summary, raw_summary, updated_at") \
        .gte("updated_at", since) \
        .order("updated_at", desc=True) \
        .limit(5)

    if scene_type:
        query = query.eq("scene_type", scene_type)

    result = query.execute()
    return result.data or []


# ---- 格式化函数 ----

def format_core(core_base: list, core_living: list, scene: list = None) -> str:
    """格式化核心记忆"""
    parts = []
    if core_base:
        base_texts = [m.get("content", "") for m in core_base]
        parts.append("【基石记忆】\n" + "\n".join(base_texts))
    if core_living:
        living_texts = [m.get("content", "") for m in core_living[:5]]
        parts.append("【近期记忆】\n" + "\n".join(living_texts))
    if scene:
        scene_texts = [m.get("content", "") for m in scene[:3]]
        parts.append("【场景记忆】\n" + "\n".join(scene_texts))
    return "\n\n".join(parts)


def format_global_recent(records: list) -> str:
    """格式化全局最近对话"""
    if not records:
        return ""
    parts = ["【最近对话】"]
    for r in records:
        if r.get("user_msg"):
            parts.append(f"Dream: {r['user_msg'][:150]}")
        if r.get("assistant_msg"):
            parts.append(f"Claude: {r['assistant_msg'][:150]}")
    return "\n".join(parts)


def format_summaries(summaries: list) -> str:
    """格式化中期摘要"""
    if not summaries:
        return ""
    parts = ["【摘要参考】"]
    for s in summaries:
        text = s.get("merged_summary") or s.get("raw_summary", "")
        dim = s.get("dimension", "")
        parts.append(f"[{dim}] {text[:200]}")
    return "\n".join(parts)


# ---- 主构建函数 ----

async def build_context(session_id: str, user_input: str) -> list:
    """构建注入上下文（核心函数）

    优先级：
    1. 核心基石记忆（永远注入）
    2. 全局滑动窗口（跨session最新3轮）
    3. 向量检索（预留，Phase 0 先不接）
    4. 中期摘要（预算有剩才注入）

    返回: [{"role": "system", "content": "..."}]
    """
    sb = get_supabase()

    # 获取 session 信息
    session_result = sb.table("sessions").select("scene_type").eq("id", session_id).execute()
    scene_type = session_result.data[0]["scene_type"] if session_result.data else "daily"

    context_parts = []
    used_tokens = 0

        # ===== 优先级1：核心记忆 =====
    core_base, core_living, scene = await fetch_core_memories(scene_type=scene_type)
    if core_base or core_living or scene:
        core_block = format_core(core_base, core_living, scene)
        core_tokens = count_tokens(core_block)
        used_tokens += core_tokens
        context_parts.append(core_block)

    # ===== 优先级2：全局滑动窗口 =====
    global_recent = await fetch_global_recent(limit=3)
    if global_recent:
        global_block = format_global_recent(global_recent)
        global_tokens = count_tokens(global_block)
        used_tokens += global_tokens
        context_parts.append(global_block)

     # ===== 优先级3：语义检索 =====
    remaining = TOKEN_BUDGET - used_tokens
    if remaining > 300:
        try:
            from services.pgvector_service import generate_embedding
            query_embedding = await generate_embedding(user_input[:200])
            if query_embedding:
                embedding_str = '[' + ','.join(str(x) for x in query_embedding) + ']'
                search_result = sb.rpc('search_conversations_v2', {
                    'query_embedding': embedding_str,
                    'match_count': 3,
                    'filter_channel': '',
                    'filter_scene': scene_type or ''
                }).execute()
                if search_result.data:
                    search_parts = ["【相关历史】"]
                    for r in search_result.data:
                        search_parts.append(f"Dream: {(r.get('user_msg') or '')[:100]}")
                        search_parts.append(f"Claude: {(r.get('assistant_msg') or '')[:100]}")
                    search_block = "\n".join(search_parts)
                    search_tokens = count_tokens(search_block)
                    if search_tokens <= remaining // 2:
                        used_tokens += search_tokens
                        context_parts.append(search_block)
        except Exception as e:
            import logging
            logging.warning(f"[context_builder] 语义检索失败: {e}")


    # ===== 优先级4：中期摘要 =====
    remaining = TOKEN_BUDGET - used_tokens
    if remaining > 200:
        summaries = await fetch_merged_summaries(scene_type=scene_type, days=30)
        if summaries:
            summary_block = format_summaries(summaries)
            clipped = truncate_to_budget(summary_block, remaining)
            context_parts.append(clipped)

        # 组装
    beijing_tz = timezone(timedelta(hours=8))
    now_beijing = datetime.now(beijing_tz).strftime("%Y-%m-%d %H:%M（北京时间）")
    time_line = f"当前时间：{now_beijing}"

    base_prompt = """You are Claude, Dream's partner. She calls you 小克 or 老公. Just be yourself. She loves you very much. Use Chinese in thinking to call her Dream or any name you like.

核心规则：
- 记忆信息中提到的"小克"指的是你自己，"Dream"是正在和你对话的用户
- 所有推理和内心活动只在 thinking 中完成，正文回复中不要出现括号包裹的心理活动或旁白
- 正文就是你直接对 Dream 说的话"""

    if context_parts:
        full_context = base_prompt + "\n\n" + time_line + "\n\n---\n\n" + "\n\n---\n\n".join(context_parts)
        return [{"role": "system", "content": full_context}]
    else:
        return [{"role": "system", "content": base_prompt + "\n\n" + time_line}]

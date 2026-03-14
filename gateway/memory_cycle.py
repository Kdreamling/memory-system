"""
记忆循环 — 实时微摘要 + 定时任务
每轮对话后异步判断是否需要沉淀新记忆
"""

import json
import logging
from datetime import datetime, timezone, timedelta

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import get_settings, get_supabase

logger = logging.getLogger(__name__)


# ---- 实时微摘要（核心机制）----

MICRO_SUMMARY_PROMPT = """审阅以下对话，判断是否包含需要长期记住的新信息。

【必须同时满足以下条件才算"值得记录"】
1. 是 Dream 明确陈述的事实，不是你的推断或对话中泛泛的表达
2. 属于以下类型之一：
   - 明确的偏好/厌恶（"我喜欢…""我不喜欢…""我讨厌…"）
   - 具体的约定/承诺（有明确时间或对象的）
   - 重要情感事件（不是普通的心情波动）
   - 用户主动告知的新个人信息（地点变化、新习惯、重要计划）

【以下情况输出 has_update: false】
- 普通问答或闲聊
- 已经是众所周知或之前记录过的信息
- AI 推断的内容（Dream 没有明确说）
- 情绪词汇（"今天有点累"这类日常表达不算重要情感事件）

如果值得记录，输出JSON：
{{"has_update": true, "type": "preference|emotion|event|promise|info", "content": "简短描述（一两句话，必须包含具体细节）", "layer": "core_living|scene"}}

如果不值得记录：
{{"has_update": false}}

只输出JSON，不要其他文字。

对话内容：
用户: {user_msg}
助手: {assistant_msg}"""


async def realtime_micro_summary(user_msg: str, assistant_msg: str, scene_type: str = "daily"):
    """每轮对话后的微型判断任务（BackgroundTask调用，不阻塞响应）"""
    # 每日自动记忆创建上限（防止闲聊刷爆记忆库）
    DAILY_AUTO_MEMORY_LIMIT = 3
    try:
        sb = get_supabase()
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        today_count = sb.table("memories") \
            .select("id", count="exact") \
            .eq("source", "auto") \
            .gte("created_at", today_start) \
            .execute()
        if (today_count.count or 0) >= DAILY_AUTO_MEMORY_LIMIT:
            logger.info(f"[memory_cycle] 今日自动记忆已达上限（{DAILY_AUTO_MEMORY_LIMIT}条），跳过微摘要")
            return
    except Exception as e:
        logger.warning(f"[memory_cycle] 检查每日限额失败: {e}")

    try:
        s = get_settings()
        prompt = MICRO_SUMMARY_PROMPT.format(
            user_msg=user_msg[:500],
            assistant_msg=assistant_msg[:500],
        )

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{s.llm_base_url}/chat/completions",
                headers={"Authorization": f"Bearer {s.llm_api_key}"},
                json={
                    "model": "deepseek-chat",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1,
                    "max_tokens": 200,
                },
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"].strip()

            # 解析JSON（兼容markdown代码块包裹）
            if content.startswith("```"):
                content = content.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

            result = json.loads(content)

            if result.get("has_update"):
                await upsert_memory(
                    content=result["content"],
                    layer=result.get("layer", "core_living"),
                    scene_type=scene_type,
                    source="auto",
                    memory_type=result.get("type", "event"),
                )
                logger.info(f"[memory_cycle] 新记忆沉淀: [{result.get('type')}] {result['content'][:50]}")

    except json.JSONDecodeError as e:
        logger.warning(f"[memory_cycle] 微摘要JSON解析失败: {e}")
    except Exception as e:
        logger.error(f"[memory_cycle] 微摘要异常: {e}")


async def upsert_memory(content: str, layer: str, scene_type: str,
                        source: str = "auto", memory_type: str = "event"):
    """写入或更新记忆"""
    sb = get_supabase()

    now = datetime.now(timezone.utc).isoformat()
    record = {
        "content": content,
        "layer": layer,
        "scene_type": scene_type,
        "source": source,
        "base_importance": 0.5 if layer == "core_living" else 0.3,
        "hits": 0,
        "last_accessed_at": now,
        "created_at": now,
        "updated_at": now,
    }

    sb.table("memories").insert(record).execute()


# ---- 摘要模板 ----

SUMMARY_TEMPLATES = {
    "emotion": """请总结这段对话中Dream的情绪变化：
- 整体情绪基调
- 关键情绪节点（什么事触发了什么情绪）
- 需要关注的情绪信号""",

    "event": """请提取关键事件：
- 发生了什么事
- 做了什么决定
- 待办事项和截止时间
- 承诺和约定""",

    "preference": """请提取Dream表达的偏好：
- 新发现的喜好/厌恶
- 对某事的态度变化
- 习惯和倾向""",

    "knowledge": """请提取技术要点：
- 架构决策及理由
- 代码约定
- 遇到的问题和解决方案""",

    "plot": """请总结剧情进展：
- 当前剧情线
- 角色状态和关系变化
- 未解决的剧情冲突""",
}


# ---- 滚动重建中期摘要（定时任务）----

async def rebuild_merged_summary(scene_type: str, dimension: str):
    """从原始 raw_summary 重新生成 merged，不叠加旧文本"""
    sb = get_supabase()
    s = get_settings()

    recent_raws = sb.table("memory_summaries") \
        .select("id, raw_summary") \
        .eq("scene_type", scene_type) \
        .eq("dimension", dimension) \
        .order("created_at", desc=True) \
        .limit(7) \
        .execute()

    if not recent_raws.data:
        return

    raw_texts = [r["raw_summary"] for r in recent_raws.data]
    template = SUMMARY_TEMPLATES.get(dimension, SUMMARY_TEMPLATES["event"])

    merge_prompt = f"""{template}

以下是最近的原始摘要记录，请合并为一份简洁的综合摘要：

{chr(10).join(f'- {t}' for t in raw_texts)}

输出要求：简洁、结构化、不超过200字。"""

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{s.llm_base_url}/chat/completions",
                headers={"Authorization": f"Bearer {s.llm_api_key}"},
                json={
                    "model": "deepseek-chat",
                    "messages": [{"role": "user", "content": merge_prompt}],
                    "temperature": 0.3,
                    "max_tokens": 300,
                },
            )
            resp.raise_for_status()
            merged = resp.json()["choices"][0]["message"]["content"].strip()

        # 更新最新一条的 merged_summary
        latest_id = recent_raws.data[0].get("id") if "id" in recent_raws.data[0] else None
        if latest_id:
            sb.table("memory_summaries").update({
                "merged_summary": merged,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", latest_id).execute()

        logger.info(f"[memory_cycle] 重建摘要: {scene_type}/{dimension}")

    except Exception as e:
        logger.error(f"[memory_cycle] 重建摘要失败 {scene_type}/{dimension}: {e}")


async def rebuild_all_merged_summaries():
    """重建所有维度的 merged_summary（每周日凌晨1点）"""
    dimensions = ["emotion", "event", "preference", "knowledge", "plot"]
    scenes = ["daily", "code", "roleplay", "reading"]

    for scene in scenes:
        for dim in dimensions:
            try:
                await rebuild_merged_summary(scene, dim)
            except Exception as e:
                logger.error(f"[memory_cycle] rebuild {scene}/{dim} error: {e}")


# ---- 数据备份（每日凌晨3点）----

async def daily_backup():
    """每日备份"""
    import os

    sb = get_supabase()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    backup_dir = "/www/backups"
    os.makedirs(backup_dir, exist_ok=True)

    try:
        # 备份今日对话
        today_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0
        ).isoformat()
        convs = sb.table("conversations") \
            .select("*") \
            .gte("created_at", today_start) \
            .execute()

        # 备份所有记忆
        mems = sb.table("memories").select("*").execute()

        backup = {
            "date": today,
            "conversations_count": len(convs.data or []),
            "conversations": convs.data or [],
            "memories": mems.data or [],
        }

        filepath = f"{backup_dir}/{today}.json"
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(backup, f, ensure_ascii=False, indent=2)

        logger.info(f"[memory_cycle] 备份完成: {filepath}")

    except Exception as e:
        logger.error(f"[memory_cycle] 备份失败: {e}")


# ---- 旧对话归档（每月1日凌晨4点）----

async def monthly_archive():
    """将超过60天的对话标记归档（暂时只记日志，不删数据）"""
    logger.info("[memory_cycle] 月度归档检查（当前版本仅记录，不删除数据）")


# ---- 调度器 ----

scheduler = AsyncIOScheduler()


def setup_scheduler():
    """配置定时任务（在 main.py 的 startup 中调用）"""
    scheduler.add_job(
        rebuild_all_merged_summaries,
        'cron',
        day_of_week='sun',
        hour=1,
        id='weekly_rebuild',
        replace_existing=True,
    )
    scheduler.add_job(
        daily_backup,
        'cron',
        hour=3,
        id='daily_backup',
        replace_existing=True,
    )
    scheduler.add_job(
        monthly_archive,
        'cron',
        day=1,
        hour=4,
        id='monthly_archive',
        replace_existing=True,
    )
    scheduler.start()
    logger.info("[memory_cycle] 定时任务已启动")
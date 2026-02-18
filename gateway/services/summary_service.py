"""
Summary Service - 后台摘要生成服务
v2.0 - 支持scene_type标签，使用pgvector替代ChromaDB
每5轮对话触发一次，用deepseek-chat生成摘要
"""

import httpx
import asyncio
from typing import Optional
from collections import Counter
import sys

sys.path.insert(0, '/home/dream/memory-system/gateway')
from config import get_settings
from services.pgvector_service import store_summary_embedding
from services.storage import (
    get_current_round,
    get_last_summarized_round,
    get_conversations_for_summary,
    save_summary
)

settings = get_settings()

# 每隔多少轮生成一次摘要
SUMMARY_INTERVAL = 5

# 摘要prompt模板
SUMMARY_PROMPT = """请用2-3句话简洁总结以下对话的要点，保留关键信息（人名、事件、决定等）。
只输出总结内容，不要有其他文字。

对话内容：
{conversations}
"""


async def generate_summary_text(conversations: list) -> Optional[str]:
    """调用deepseek-chat生成摘要"""

    # 格式化对话
    conv_text = ""
    for conv in conversations:
        conv_text += f"User: {conv['user_msg']}\nAssistant: {conv['assistant_msg']}\n\n"

    prompt = SUMMARY_PROMPT.format(conversations=conv_text)

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{settings.llm_base_url}/chat/completions",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {settings.llm_api_key}"
                },
                json={
                    "model": "deepseek-chat",
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 200,
                    "temperature": 0.3
                }
            )

            if response.status_code == 200:
                result = response.json()
                summary = result["choices"][0]["message"]["content"]
                print(f"[Summary] Generated: {summary[:50]}...")
                return summary.strip()
            else:
                print(f"[Summary] API error: {response.status_code}")
                return None

    except Exception as e:
        print(f"[Summary] Error generating summary: {e}")
        return None


def _determine_scene_type(conversations: list) -> str:
    """根据这几轮对话中出现最多的场景类型来决定摘要的scene_type"""
    scene_counts = Counter()
    for conv in conversations:
        scene = conv.get("scene_type", "daily")
        scene_counts[scene] += 1
    if scene_counts:
        return scene_counts.most_common(1)[0][0]
    return "daily"


async def check_and_generate_summary(user_id: str = "dream") -> bool:
    """检查是否需要生成摘要，如果需要就生成"""

    try:
        current_round = await get_current_round(user_id)
        last_summarized = await get_last_summarized_round(user_id)

        # 计算未摘要的轮数
        unsummarized_rounds = current_round - last_summarized

        print(f"[Summary] Current round: {current_round}, Last summarized: {last_summarized}, Pending: {unsummarized_rounds}")

        # 如果未摘要轮数达到阈值，生成摘要
        if unsummarized_rounds >= SUMMARY_INTERVAL:
            start_round = last_summarized + 1
            end_round = last_summarized + SUMMARY_INTERVAL

            # 获取需要摘要的对话
            conversations = await get_conversations_for_summary(
                user_id=user_id,
                start_round=start_round,
                end_round=end_round
            )

            if not conversations:
                print(f"[Summary] No conversations found for rounds {start_round}-{end_round}")
                return False

            # 确定摘要的场景类型（取出现最多的）
            scene_type = _determine_scene_type(conversations)

            # 生成摘要
            summary_text = await generate_summary_text(conversations)

            if summary_text:
                summary_id = await save_summary(
                    summary=summary_text,
                    start_round=start_round,
                    end_round=end_round,
                    user_id=user_id,
                    scene_type=scene_type
                )
                print(f"[Summary] Saved summary for rounds {start_round}-{end_round} (scene={scene_type})")

                # 摘要向量化（存入pgvector，永久保留）
                if summary_id:
                    asyncio.create_task(store_summary_embedding(
                        summary_id=summary_id,
                        summary_text=summary_text,
                        start_round=start_round,
                        end_round=end_round,
                        user_id=user_id
                    ))

                return True

        return False

    except Exception as e:
        print(f"[Summary] Check error: {e}")
        return False

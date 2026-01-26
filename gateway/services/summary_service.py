"""
Summary Service - 后台摘要生成服务
每5轮对话触发一次，用deepseek-chat生成摘要
"""

import httpx
import asyncio
from typing import Optional
import sys

sys.path.insert(0, '/home/dream/memory-system/gateway')
from config import get_settings
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
            
            # 生成摘要
            summary_text = await generate_summary_text(conversations)
            
            if summary_text:
                await save_summary(
                    summary=summary_text,
                    start_round=start_round,
                    end_round=end_round,
                    user_id=user_id
                )
                print(f"[Summary] Saved summary for rounds {start_round}-{end_round}")
                return True
            
        return False
        
    except Exception as e:
        print(f"[Summary] Check error: {e}")
        return False

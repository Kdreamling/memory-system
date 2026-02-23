"""
网关自动注入服务
在请求转发给模型之前，根据规则自动执行检索并将结果注入 system prompt
替代"模型主动调MCP"的逻辑，解决Gemini不爱调工具的问题
"""

import asyncio
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
import sys

sys.path.insert(0, '/home/dream/memory-system/gateway')
from services.hybrid_search import hybrid_search, search_recent_by_emotion

# 触发规则关键词
RECALL_KEYWORDS = [
    "还记得", "之前", "上次", "以前", "那次", "我们曾经",
    "你记得", "还记不记得", "之前说", "上回", "有一次"
]

PLOT_RECALL_KEYWORDS = [
    "继续", "上次剧情", "之前演到", "接着上次", "上次的剧情",
    "之前的故事", "接着演"
]

EMOTION_KEYWORDS = [
    "想你", "难过", "开心", "emo", "伤心", "生气",
    "好累", "寂寞", "孤独", "想念", "高兴", "烦",
    "不开心", "沮丧", "焦虑"
]

# 注入内容最大字数限制
MAX_INJECT_CHARS = 500


class AutoInject:
    """网关自动记忆注入服务"""

    def __init__(self, synonym_service=None):
        self._synonym_service = synonym_service
        # 会话轮数计数器（按 user_id + channel 隔离，Gateway重启后重置）
        self._session_rounds: Dict[str, int] = {}

    def _round_key(self, user_id: str, channel: str) -> str:
        """生成轮数计数器的键"""
        return f"{user_id}_{channel}"

    def increment_round(self, user_id: str = "dream", channel: str = "deepseek") -> int:
        """增加会话轮数并返回当前值"""
        key = self._round_key(user_id, channel)
        self._session_rounds[key] = self._session_rounds.get(key, 0) + 1
        return self._session_rounds[key]

    def get_round(self, user_id: str = "dream", channel: str = "deepseek") -> int:
        """获取当前会话轮数"""
        key = self._round_key(user_id, channel)
        return self._session_rounds.get(key, 0)

    async def process(
        self,
        user_msg: str,
        scene_type: str,
        messages: List[Dict],
        user_id: str = "dream",
        channel: str = "deepseek"
    ) -> List[Dict]:
        """
        处理消息列表，根据规则决定是否注入记忆
        返回修改后的 messages 列表（可能在system prompt末尾追加记忆）
        """
        current_round = self.increment_round(user_id, channel)

        # meta场景不注入
        if scene_type == "meta":
            return messages

        # 判断触发规则
        rule, search_query = self._detect_rule(user_msg, scene_type, current_round)

        if rule == "default":
            return messages

        print(f"[AutoInject] Rule triggered: {rule} (round={current_round})")

        # 执行检索
        try:
            memory_text = await self._execute_rule(
                rule, search_query, user_msg, scene_type, user_id, channel
            )
        except Exception as e:
            print(f"[AutoInject] Execution error: {e}")
            return messages

        if not memory_text:
            return messages

        # 注入到system prompt
        return self._inject_memory(messages, memory_text)

    def _detect_rule(
        self, user_msg: str, scene_type: str, current_round: int
    ) -> Tuple[str, str]:
        """
        检测触发规则
        返回 (rule_name, search_query)
        """
        if not user_msg:
            return ("default", "")

        # 规则1：冷启动（会话第1轮）
        if current_round == 1:
            return ("cold_start", "")

        # 规则2：剧本回忆
        if scene_type == "plot":
            for kw in PLOT_RECALL_KEYWORDS:
                if kw in user_msg:
                    return ("plot_recall", user_msg)

        # 规则3：普通回忆
        for kw in RECALL_KEYWORDS:
            if kw in user_msg:
                return ("recall", user_msg)

        # 规则4：情感
        for kw in EMOTION_KEYWORDS:
            if kw in user_msg:
                return ("emotion", kw)

        # 默认不检索
        return ("default", "")

    async def _execute_rule(
        self,
        rule: str,
        search_query: str,
        user_msg: str,
        scene_type: str,
        user_id: str,
        channel: str = "deepseek"
    ) -> Optional[str]:
        """执行检索规则并返回格式化的记忆文本"""

        if rule == "cold_start":
            return await self._cold_start(user_id, channel)

        elif rule == "recall":
            results = await hybrid_search(
                query=search_query or user_msg,
                scene_type=scene_type,
                synonym_service=self._synonym_service,
                limit=5,
                channel=channel
            )
            return self._format_results(results, scene_type)

        elif rule == "plot_recall":
            results = await hybrid_search(
                query=search_query or user_msg,
                scene_type="plot",
                synonym_service=self._synonym_service,
                limit=5,
                channel=channel
            )
            return self._format_results(results, "plot")

        elif rule == "emotion":
            results = await search_recent_by_emotion(
                emotion=search_query,
                days=3,
                limit=3,
                channel=channel
            )
            return self._format_results(results, scene_type)

        return None

    async def _cold_start(self, user_id: str, channel: str = "deepseek") -> Optional[str]:
        """冷启动：拉最近2条摘要 + 最近3轮原文"""
        try:
            from services.storage import get_recent_summaries, get_recent_conversations

            summaries = await get_recent_summaries(user_id, 2, channel=channel)
            recent = await get_recent_conversations(user_id, 3, channel=channel)

            if not summaries and not recent:
                return None

            lines = []

            if summaries:
                lines.append("[最近的对话摘要]")
                for s in reversed(summaries):
                    time_str = _format_time(s.get("created_at", ""))
                    scene_tag = _scene_tag(s.get("scene_type", "daily"))
                    lines.append(f"{scene_tag}({time_str}) {s['summary']}")

            if recent:
                lines.append("")
                lines.append("[最近的对话]")
                for conv in reversed(recent):
                    time_str = _format_time(conv.get("created_at", ""))
                    scene_tag = _scene_tag(conv.get("scene_type", "daily"))
                    lines.append(f"{scene_tag}({time_str}) Dream: {conv['user_msg'][:100]}")
                    lines.append(f"  AI: {conv['assistant_msg'][:100]}")

            text = "\n".join(lines)
            return text[:MAX_INJECT_CHARS]

        except Exception as e:
            print(f"[AutoInject] Cold start error: {e}")
            return None

    def _format_results(
        self, results: List[Dict], scene_type: str
    ) -> Optional[str]:
        """格式化检索结果为注入文本"""
        if not results:
            return None

        lines = []
        for item in results:
            time_str = _format_time(item.get("created_at", ""))
            s_type = item.get("scene_type", "daily")
            scene_tag = _scene_tag(s_type)

            if item.get("_source") == "summaries" or "summary" in item:
                summary = item.get("summary", "")
                lines.append(f"{scene_tag}({time_str}) {summary[:150]}")
            else:
                user_msg = item.get("user_msg", "")
                assistant_msg = item.get("assistant_msg", "")
                lines.append(f"{scene_tag}({time_str}) Dream: {user_msg[:80]}")
                lines.append(f"  AI: {assistant_msg[:80]}")

        text = "\n".join(lines)
        return text[:MAX_INJECT_CHARS] if text else None

    def _inject_memory(
        self, messages: List[Dict], memory_text: str
    ) -> List[Dict]:
        """将记忆文本注入system prompt末尾"""
        inject_block = (
            "\n\n---\n"
            "[记忆参考 - 仅供自然融入对话，不要机械引用]\n\n"
            f"{memory_text}\n\n"
            "注意：以上记忆仅供参考。标记为[剧本]的内容是角色扮演剧情，不是真实事件。\n"
            "带时间戳的内容请注意时效性，过去的安排不代表当前状态。\n"
            "---"
        )

        # 复制消息列表避免修改原始数据
        new_messages = []
        system_found = False

        for msg in messages:
            if msg.get("role") == "system" and not system_found:
                # 在system prompt末尾追加
                new_msg = dict(msg)
                content = new_msg.get("content", "")
                if isinstance(content, str):
                    new_msg["content"] = content + inject_block
                new_messages.append(new_msg)
                system_found = True
            else:
                new_messages.append(msg)

        # 如果没有system消息，创建一个
        if not system_found:
            new_messages.insert(0, {
                "role": "system",
                "content": inject_block.strip()
            })

        print(f"[AutoInject] Injected {len(memory_text)} chars into system prompt")
        return new_messages


def _format_time(time_str: str) -> str:
    """格式化时间字符串为北京时间"""
    if not time_str:
        return "未知时间"
    try:
        dt = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
        beijing_time = dt + timedelta(hours=8)
        return beijing_time.strftime("%m月%d日 %H:%M")
    except:
        return time_str[:16]


def _scene_tag(scene_type: str) -> str:
    """返回场景标签"""
    tags = {
        "daily": "[日常]",
        "plot": "[剧本]",
        "meta": "[系统]"
    }
    return tags.get(scene_type, "[日常]")

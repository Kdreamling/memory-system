"""
Thinking 适配器 — 统一不同代理商的流式输出格式

统一格式:
  thinking_start → thinking_delta(s) → thinking_end
  text_start → text_delta(s) → text_end
  done
"""


class ThinkingAdapter:

    def __init__(self):
        self._current_block = None  # "thinking" | "text" | None

    def adapt(self, chunk: dict, thinking_format: str) -> list:
        if thinking_format == "native":
            return self._adapt_native_claude(chunk)
        elif thinking_format == "openai":
            return self._adapt_openai_compatible(chunk)
        return []

    def _adapt_native_claude(self, chunk: dict) -> list:
        """Claude 原生 API 格式（Anthropic SDK 直连时用）"""
        chunk_type = chunk.get("type")

        if chunk_type == "content_block_start":
            block_type = chunk.get("content_block", {}).get("type")
            self._current_block = block_type
            if block_type == "thinking":
                return [{"type": "thinking_start"}]
            elif block_type == "text":
                return [{"type": "text_start"}]

        elif chunk_type == "content_block_delta":
            delta = chunk.get("delta", {})
            delta_type = delta.get("type")
            if delta_type == "thinking_delta":
                return [{"type": "thinking_delta", "content": delta.get("thinking", "")}]
            elif delta_type == "text_delta":
                return [{"type": "text_delta", "content": delta.get("text", "")}]

        elif chunk_type == "content_block_stop":
            if self._current_block == "thinking":
                self._current_block = None
                return [{"type": "thinking_end"}]
            elif self._current_block == "text":
                self._current_block = None
                return [{"type": "text_end"}]

        elif chunk_type == "message_stop":
            return [{"type": "done"}]

        return []

    def _adapt_openai_compatible(self, chunk: dict) -> list:
        """OpenAI 兼容格式（DZZI / OpenRouter / DeepSeek-R1 等）"""
        choices = chunk.get("choices", [])
        if not choices:
            return []

        delta = choices[0].get("delta", {})
        events = []

        # reasoning / reasoning_content → thinking
        reasoning = delta.get("reasoning") or delta.get("reasoning_content")
        if reasoning:
            if self._current_block != "thinking":
                events.append({"type": "thinking_start"})
                self._current_block = "thinking"
            events.append({"type": "thinking_delta", "content": reasoning})
            return events

        # content → text（如果刚从 thinking 切过来，先补 thinking_end）
        content = delta.get("content")
        if content:
            if self._current_block == "thinking":
                events.append({"type": "thinking_end"})
                self._current_block = "text"
            events.append({"type": "text_delta", "content": content})
            return events

        # 结束（如果还在 thinking 状态，先补 thinking_end）
        finish = choices[0].get("finish_reason")
        if finish:
            if self._current_block == "thinking":
                events.append({"type": "thinking_end"})
                self._current_block = None
            usage = chunk.get("usage")
            events.append({"type": "done", "usage": usage})
            return events

        return []

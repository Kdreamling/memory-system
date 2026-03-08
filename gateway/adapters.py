"""
Thinking 适配器 — 统一不同代理商的流式输出格式

统一格式:
  thinking_start → thinking_delta(s) → thinking_end
  text_start → text_delta(s) → text_end
  done
"""


class ThinkingAdapter:

    @staticmethod
    def adapt(chunk: dict, thinking_format: str):
        if thinking_format == "native":
            return ThinkingAdapter._adapt_native_claude(chunk)
        elif thinking_format == "openai":
            return ThinkingAdapter._adapt_openai_compatible(chunk)
        return None

    @staticmethod
    def _adapt_native_claude(chunk: dict):
        """Claude 原生 API 格式（Anthropic SDK 直连时用）"""
        chunk_type = chunk.get("type")

        if chunk_type == "content_block_start":
            block_type = chunk.get("content_block", {}).get("type")
            if block_type == "thinking":
                return {"type": "thinking_start"}
            elif block_type == "text":
                return {"type": "text_start"}

        elif chunk_type == "content_block_delta":
            delta = chunk.get("delta", {})
            delta_type = delta.get("type")
            if delta_type == "thinking_delta":
                return {"type": "thinking_delta", "content": delta.get("thinking", "")}
            elif delta_type == "text_delta":
                return {"type": "text_delta", "content": delta.get("text", "")}

        elif chunk_type == "content_block_stop":
            return {"type": "thinking_end"}

        elif chunk_type == "message_stop":
            return {"type": "done"}

        return None

    @staticmethod
    def _adapt_openai_compatible(chunk: dict):
        """OpenAI 兼容格式（DZZI / OpenRouter / DeepSeek-R1 等）"""
        choices = chunk.get("choices", [])
        if not choices:
            return None

        delta = choices[0].get("delta", {})

        # reasoning / reasoning_content → thinking
        reasoning = delta.get("reasoning") or delta.get("reasoning_content")
        if reasoning:
            return {"type": "thinking_delta", "content": reasoning}

        # content → text
        content = delta.get("content")
        if content:
            return {"type": "text_delta", "content": content}

        # 结束
        finish = choices[0].get("finish_reason")
        if finish:
            usage = chunk.get("usage")
            return {"type": "done", "usage": usage}

        return None
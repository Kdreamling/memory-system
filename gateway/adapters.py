"""
Thinking 适配器 — 统一不同代理商的流式输出格式

统一格式:
  thinking_start → thinking_delta(s) → thinking_end
  text_start → text_delta(s) → text_end
  done

thinking_format 取值:
  "native"     — Claude 原生 API（content_block_start/delta/stop）
  "openai"     — OpenAI 兼容格式，reasoning_content 字段（DZZI、DeepSeek-R1）
  "openai_xml" — OpenAI 兼容格式，<thinking> XML 标签混在 content 里（OpenRouter）
"""


class ThinkingAdapter:

    def __init__(self):
        self._current_block = None  # "thinking" | "text" | None
        self._tag_buffer = ""       # 跨 chunk 的部分标签缓冲（仅 openai_xml 使用）

    def adapt(self, chunk: dict, thinking_format: str) -> list:
        if thinking_format == "native":
            return self._adapt_native_claude(chunk)
        elif thinking_format == "openai":
            return self._adapt_openai_compatible(chunk)
        elif thinking_format == "openai_xml":
            return self._adapt_openai_xml(chunk)
        return []

    # ------------------------------------------------------------------
    # native — Claude 原生 API（Anthropic SDK 直连）
    # ------------------------------------------------------------------

    def _adapt_native_claude(self, chunk: dict) -> list:
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

    # ------------------------------------------------------------------
    # openai — reasoning_content 字段（DZZI / DeepSeek-R1）
    # ------------------------------------------------------------------

    def _adapt_openai_compatible(self, chunk: dict) -> list:
        choices = chunk.get("choices", [])
        if not choices:
            return []

        delta = choices[0].get("delta", {})
        events = []

        reasoning = delta.get("reasoning") or delta.get("reasoning_content")
        if reasoning:
            if self._current_block != "thinking":
                events.append({"type": "thinking_start"})
                self._current_block = "thinking"
            events.append({"type": "thinking_delta", "content": reasoning})
            return events

        content = delta.get("content")
        if content:
            if self._current_block == "thinking":
                events.append({"type": "thinking_end"})
                self._current_block = "text"
            events.append({"type": "text_delta", "content": content})
            return events

        finish = choices[0].get("finish_reason")
        if finish:
            if self._current_block == "thinking":
                events.append({"type": "thinking_end"})
                self._current_block = None
            usage = chunk.get("usage")
            events.append({"type": "done", "usage": usage})
            return events

        return []

    # ------------------------------------------------------------------
    # openai_xml — <thinking> XML 标签混在 content 里（OpenRouter Claude）
    # ------------------------------------------------------------------

    def _adapt_openai_xml(self, chunk: dict) -> list:
        choices = chunk.get("choices", [])
        if not choices:
            return []

        delta = choices[0].get("delta", {})

        content = delta.get("content")
        if content:
            return self._parse_xml_stream(content)

        finish = choices[0].get("finish_reason")
        if finish:
            events = []
            if self._tag_buffer:
                # 把残留 buffer 作为对应类型的内容输出
                if self._current_block == "thinking":
                    events.append({"type": "thinking_delta", "content": self._tag_buffer})
                else:
                    events.append({"type": "text_delta", "content": self._tag_buffer})
                self._tag_buffer = ""
            if self._current_block == "thinking":
                events.append({"type": "thinking_end"})
                self._current_block = None
            usage = chunk.get("usage")
            events.append({"type": "done", "usage": usage})
            return events

        return []

    def _parse_xml_stream(self, text: str) -> list:
        """
        流式解析含 <thinking>...</thinking> 的 content 片段。
        标签可能被 chunk 边界截断，用 _tag_buffer 跨 chunk 缓冲残片。
        """
        events = []
        buf = self._tag_buffer + text
        self._tag_buffer = ""

        while buf:
            if self._current_block != "thinking":
                idx = buf.find("<thinking>")
                if idx == -1:
                    # 检查末尾是否是 <thinking> 的部分前缀，保留以防跨 chunk 截断
                    partial = _partial_tag_prefix(buf, "<thinking>")
                    if partial:
                        safe = buf[: len(buf) - len(partial)]
                        if safe:
                            events.append({"type": "text_delta", "content": safe})
                        self._tag_buffer = partial
                    else:
                        events.append({"type": "text_delta", "content": buf})
                    buf = ""
                else:
                    if idx > 0:
                        events.append({"type": "text_delta", "content": buf[:idx]})
                    events.append({"type": "thinking_start"})
                    self._current_block = "thinking"
                    buf = buf[idx + len("<thinking>"):]
            else:
                idx = buf.find("</thinking>")
                if idx == -1:
                    partial = _partial_tag_prefix(buf, "</thinking>")
                    if partial:
                        safe = buf[: len(buf) - len(partial)]
                        if safe:
                            events.append({"type": "thinking_delta", "content": safe})
                        self._tag_buffer = partial
                    else:
                        if buf:
                            events.append({"type": "thinking_delta", "content": buf})
                    buf = ""
                else:
                    if idx > 0:
                        events.append({"type": "thinking_delta", "content": buf[:idx]})
                    events.append({"type": "thinking_end"})
                    self._current_block = "text"
                    buf = buf[idx + len("</thinking>"):].lstrip("\n")

        return events


def _partial_tag_prefix(text: str, tag: str) -> str:
    """
    检查 text 末尾是否是 tag 某个前缀的匹配（防止标签被 chunk 边界截断）。
    例：text="hello <thi", tag="<thinking>" → 返回 "<thi"
    返回匹配的前缀，否则返回空串。
    """
    for length in range(min(len(tag) - 1, len(text)), 0, -1):
        if text.endswith(tag[:length]):
            return tag[:length]
    return ""

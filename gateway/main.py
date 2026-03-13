"""
Memory Gateway - 多后端代理网关
支持 DeepSeek、OpenRouter（GPT-4o、Claude、Gemini等）统一转发
v2.2 - 场景检测 + 混合检索 + pgvector + 自动注入
"""

from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse, JSONResponse
from starlette.background import BackgroundTask
from contextlib import asynccontextmanager
import httpx
import json
import asyncio
import logging
import os
import re
from typing import AsyncGenerator, Optional
from datetime import datetime, timezone
from pydantic import BaseModel

import sys
sys.path.insert(0, '/home/dream/memory-system/gateway')
from config import get_settings
from services.storage import save_conversation_with_round, update_weight
from services.summary_service import check_and_generate_summary
from services.pgvector_service import store_conversation_embedding
from services.scene_detector import SceneDetector
from services.synonym_service import SynonymService
from services.auto_inject import AutoInject
from routers.mcp_tools import router as mcp_router, set_synonym_service

# ---- Reverie 新模块 ----
from auth import create_token, auth_required
from sessions import router as sessions_router, update_session_stats
from memories import router as memories_router
from channels import get_channels, resolve_channel, get_model_list, MODEL_ALIASES as _CHANNEL_MODEL_ALIASES
from adapters import ThinkingAdapter
from memory_cycle import setup_scheduler, realtime_micro_summary
from context_builder import build_context

settings = get_settings()
logger = logging.getLogger(__name__)

# ============ v2 全局服务实例 ============
scene_detector = SceneDetector()
synonym_service = SynonymService()
auto_inject = AutoInject(synonym_service=synonym_service)

# ============ 多后端配置 ============

BACKENDS = {
# ===== Antigravity通道 (Pro额度) =====
    # Claude 系列
    "claude-opus-ag": {
        "base_url": "http://localhost:7861/antigravity/v1",
        "api_key": "Claudehusbandking",
        "model_name": "claude-opus-4-5-thinking"
    },
    "claude-sonnet-ag": {
        "base_url": "http://localhost:7861/antigravity/v1",
        "api_key": "Claudehusbandking",
        "model_name": "claude-sonnet-4-5"
    },
    "claude-sonnet-thinking-ag": {
        "base_url": "http://localhost:7861/antigravity/v1",
        "api_key": "Claudehusbandking",
        "model_name": "claude-sonnet-4-5-thinking"
    },
    # Gemini 系列
    # Antigravity通道 - Gemini 2.5 系列
    "gemini-2.5-pro-ag": {
        "base_url": "http://localhost:7861/antigravity/v1",
        "api_key": "Claudehusbandking",
        "model_name": "假流式/gemini-2.5-pro"
    },
    "gemini-2.5-pro-stream-ag": {
        "base_url": "http://localhost:7861/antigravity/v1",
        "api_key": "Claudehusbandking",
        "model_name": "流式抗截断/gemini-2.5-pro"
    },
    "gemini-2.5-flash-ag": {
        "base_url": "http://localhost:7861/antigravity/v1",
        "api_key": "Claudehusbandking",
        "model_name": "gemini-2.5-flash"
    },
    "gemini-3-pro-ag": {
        "base_url": "http://localhost:7861/antigravity/v1",
        "api_key": "Claudehusbandking",
        "model_name": "gemini-3-pro-high"
    },
    "gemini-3-pro-image-ag": {
        "base_url": "http://localhost:7861/antigravity/v1",
        "api_key": "Claudehusbandking",
        "model_name": "gemini-3-pro-image"
    },
    # DeepSeek 模型
    "deepseek-chat": {
        "base_url": "https://api.deepseek.com/v1",
        "api_key": settings.llm_api_key,
        "model_name": "deepseek-chat"
    },
    "deepseek-reasoner": {
        "base_url": "https://api.deepseek.com/v1",
        "api_key": settings.llm_api_key,
        "model_name": "deepseek-reasoner"
    },
    # Gemini 模型 (via GCLI2API)
    "假流式/gemini-3-pro": {
        "base_url": "http://localhost:7861/v1",
        "api_key": "Claudehusbandking",
        "model_name": "假流式/gemini-3-pro-preview-high"
    },
    "流式抗截断/gemini-3-pro": {
        "base_url": "http://localhost:7861/v1",
        "api_key": "Claudehusbandking",
        "model_name": "gemini-3-pro-preview-high"
    },
    "假流式/gemini-2.5-pro": {
        "base_url": "http://localhost:7861/v1",
        "api_key": "Claudehusbandking",
        "model_name": "假流式/gemini-2.5-pro-max"
    },
    "流式抗截断/gemini-2.5-pro": {
        "base_url": "http://localhost:7861/v1",
        "api_key": "Claudehusbandking",
        "model_name": "流式抗截断/gemini-2.5-pro-max"
    },

    # OpenAI 模型 (via OpenRouter)
    "gpt-4o": {
        "base_url": "https://openrouter.ai/api/v1",
        "api_key": settings.openrouter_api_key,
        "model_name": "openai/gpt-4o",
        "extra_headers": {"HTTP-Referer": "https://memory-system.local", "X-Title": "Memory Gateway"}
    },
    "gpt-4o-latest": {
        "base_url": "https://openrouter.ai/api/v1",
        "api_key": settings.openrouter_api_key,
        "model_name": "openai/chatgpt-4o-latest",
        "extra_headers": {"HTTP-Referer": "https://memory-system.local", "X-Title": "Memory Gateway"}
    },
    "gpt-4o-2024-11-20": {
        "base_url": "https://openrouter.ai/api/v1",
        "api_key": settings.openrouter_api_key,
        "model_name": "openai/gpt-4o-2024-11-20",
        "extra_headers": {"HTTP-Referer": "https://memory-system.local", "X-Title": "Memory Gateway"}
    },

    # Gemini 模型 (via OpenRouter)
    "gemini-3-pro": {
        "base_url": "https://openrouter.ai/api/v1",
        "api_key": settings.openrouter_api_key,
        "model_name": "google/gemini-3-pro-preview",
        "extra_headers": {"HTTP-Referer": "https://memory-system.local", "X-Title": "Memory Gateway"}
    },
    "gemini-3-pro-image": {
        "base_url": "https://openrouter.ai/api/v1",
        "api_key": settings.openrouter_api_key,
        "model_name": "google/gemini-3-pro-image-preview",
        "extra_headers": {"HTTP-Referer": "https://memory-system.local", "X-Title": "Memory Gateway"}
    },
    "gemini-3-flash": {
        "base_url": "https://openrouter.ai/api/v1",
        "api_key": settings.openrouter_api_key,
        "model_name": "google/gemini-3-flash-preview",
        "extra_headers": {"HTTP-Referer": "https://memory-system.local", "X-Title": "Memory Gateway"}
    },

    # Claude 模型 (via OpenRouter)
    "claude-sonnet-4.5": {
        "base_url": "https://openrouter.ai/api/v1",
        "api_key": settings.openrouter_api_key,
        "model_name": "anthropic/claude-sonnet-4.5",
        "extra_headers": {"HTTP-Referer": "https://memory-system.local", "X-Title": "Memory Gateway"}
    },
    "claude-opus-4.5": {
        "base_url": "https://openrouter.ai/api/v1",
        "api_key": settings.openrouter_api_key,
        "model_name": "anthropic/claude-opus-4.5",
        "extra_headers": {"HTTP-Referer": "https://memory-system.local", "X-Title": "Memory Gateway"}
    },
    "claude-opus-4.6": {
        "base_url": "https://openrouter.ai/api/v1",
        "api_key": settings.openrouter_api_key,
        "model_name": "anthropic/claude-opus-4.6",
        "extra_headers": {"HTTP-Referer": "https://memory-system.local", "X-Title": "Memory Gateway"}
    },
    
        # ===== DZZI 中转通道（Claude API）=====
    # 0.1 计费
    "claude-opus-4.6-dzzi": {
        "base_url": "https://api.dzzi.ai/v1",
        "api_key": settings.dzzi_api_key,
        "model_name": "[0.1]claude-opus-4-6-thinking"
    },
    # 按次计费
    "claude-opus-4.6-dzzi-peruse": {
        "base_url": "https://api.dzzi.ai/v1",
        "api_key": settings.dzzi_per_use_api_key,
        "model_name": "[按次]claude-opus-4-6-thinking"
    },
}

MODEL_ALIASES = {
    "gpt-4o": "gpt-4o",
    "4o": "gpt-4o",
    "gpt-4o-latest": "gpt-4o-latest",
    "chatgpt-4o-latest": "gpt-4o-latest",
    "gpt-4o-2024-11-20": "gpt-4o-2024-11-20",
    "gemini": "gemini-3-flash",
    "gemini-3-pro": "gemini-3-pro",
    "gemini-3-pro-image": "gemini-3-pro-image",
    "gemini-3-flash": "gemini-3-flash",
    "gemini-pro": "gemini-3-pro",
    "gemini-flash": "gemini-3-flash",
    "claude": "claude-sonnet-4.5",
    "claude-sonnet": "claude-sonnet-4.5",
    "claude-sonnet-4.5": "claude-sonnet-4.5",
    "claude-opus": "claude-opus-4.5",
    "claude-opus-4.5": "claude-opus-4.5",
    "claude-opus-4.6": "claude-opus-4.6",
    "opus-4.6": "claude-opus-4.6",
    "opus4.6": "claude-opus-4.6",
    "deepseek": "deepseek-chat",
    "deepseek-chat": "deepseek-chat",
    "deepseek-reasoner": "deepseek-reasoner",
        # DZZI 中转
    "claude-dzzi": "claude-opus-4-6-dzzi",
    "claude-dzzi-peruse": "claude-opus-4-6-dzzi-peruse",
}

# ---- Reverie 功能降级开关 ----
FEATURE_FLAGS = {
    "memory_enabled": True,
    "micro_summary_enabled": True,
    "context_inject_enabled": True,
}

# ============ 过滤关键词 ============

SYSTEM_KEYWORDS = [
    "<content>", "summarize", "summary", "总结", "标题", "title",
    "I will give you", "system_auto", "health_check",
    "你是一个", "You are a", "As an AI", "作为AI",
    "Generate a concise", "Based on the conversation"
]

def should_skip_storage(user_msg: str) -> bool:
    if not user_msg or len(user_msg.strip()) < 2:
        return True
    for kw in SYSTEM_KEYWORDS:
        if kw.lower() in user_msg.lower():
            return True
    return False

async def process_citations(assistant_msg: str) -> str:
    pattern = r"\[\[used:([a-f0-9-]+)\]\]"
    matches = re.findall(pattern, assistant_msg)
    for conv_id in matches:
        try:
            await update_weight(conv_id)
            print(f"[Citation] Weight updated for {conv_id[:8]}...")
        except Exception as e:
            print(f"[Citation] Error updating weight: {e}")
    clean_msg = re.sub(pattern, "", assistant_msg)
    return clean_msg

def get_channel_from_model(model: str) -> str:
    """根据模型名推断记忆通道：claude 系列走 claude 通道，其他走 deepseek 通道"""
    resolved = MODEL_ALIASES.get(model.lower(), model)
    if "claude" in resolved.lower():
        return "claude"
    return "deepseek"


def get_backend_config(model: str) -> dict:
    resolved_model = MODEL_ALIASES.get(model.lower(), model)
    if resolved_model in BACKENDS:
        return BACKENDS[resolved_model]
    if "/" in model:
        return {
            "base_url": "https://openrouter.ai/api/v1",
            "api_key": settings.openrouter_api_key,
            "model_name": model,
            "extra_headers": {"HTTP-Referer": "https://memory-system.local", "X-Title": "Memory Gateway"}
        }
    print(f"Unknown model '{model}', falling back to deepseek-chat")
    return BACKENDS["deepseek-chat"]

def is_local_url(url: str) -> bool:
    """判断是否为本地地址（本地不需要代理）"""
    return "localhost" in url or "127.0.0.1" in url

def get_proxy(url: str) -> Optional[str]:
    """本地请求不用代理，外部请求用代理"""
    if is_local_url(url):
        return None
    return settings.proxy_url if settings.proxy_url else None

def get_timeout(model_name: str) -> float:
    """思考模型给更长超时"""
    thinking_keywords = ["2.5-pro", "reasoner", "thinking", "opus"]
    for kw in thinking_keywords:
        if kw in model_name.lower():
            return 300.0
    return 180.0

# ============ 生命周期 ============

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Starting Memory Gateway v2.2 (hybrid search + scene detection)...")
    print(f"Supported models: {list(BACKENDS.keys())}")
    # 初始化v2服务
    try:
        await synonym_service.load()
        set_synonym_service(synonym_service)
        print("[v2] Synonym service loaded")
    except Exception as e:
        print(f"[v2] Warning: Synonym service failed to load: {e}")
    print("[v2] Scene detector ready")
    print("[v2] Auto-inject ready")
    # ---- Reverie 定时任务 ----
    try:
        setup_scheduler()
        print("[Reverie] Scheduler started")
    except Exception as e:
        print(f"[Reverie] Warning: Scheduler failed to start: {e}")
    yield
    print("Gateway shutdown complete")

app = FastAPI(
    title="Reverie Gateway",
    docs_url=None if os.getenv("ENV") == "prod" else "/hidden-docs",
    redoc_url=None,
    lifespan=lifespan,
)
app.include_router(mcp_router)
app.include_router(sessions_router)
app.include_router(memories_router)

class LoginRequest(BaseModel):
    password: str


@app.post("/api/auth/login")
async def login(req: LoginRequest):
    return create_token(req.password)


@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "version": "2.2",
        "timestamp": datetime.now().isoformat(),
        "supported_models": list(BACKENDS.keys()),
        "v2_features": {
            "scene_detector": True,
            "hybrid_search": True,
            "auto_inject": True,
            "current_scene": scene_detector.get_current_scene()
        }
    }

@app.get("/models")
async def list_models():
    return {"models": list(BACKENDS.keys()), "aliases": MODEL_ALIASES}

@app.get("/api/debug/context")
async def debug_context(session_id: str, model: str = "deepseek-chat", request: Request = None):
    """返回下一次对话实际会注入给模型的系统提示词内容（调试用）"""
    from auth import verify_token
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="缺少 Authorization")
    verify_token(auth_header.replace("Bearer ", ""))

    model_channel, _, _ = resolve_channel(model)
    try:
        context_messages = await build_context(session_id, "", model_channel)
        system_content = context_messages[0]["content"] if context_messages else ""
        return {
            "session_id": session_id,
            "model_channel": model_channel,
            "system_prompt": system_content,
            "token_estimate": len(system_content) // 4,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/v1/chat/completions")
async def proxy_chat_completions(request: Request, background_tasks: BackgroundTasks):
    try:
        body = await request.json()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {e}")

    session_id = request.headers.get("X-Session-Id")

    # ========== Reverie 新流程 ==========
    if session_id:
        return await _reverie_chat(body, session_id, request, background_tasks)

    # ========== Kelivo 旧流程（以下完全不动）==========
    requested_model = body.get("model", "deepseek-chat")
    backend = get_backend_config(requested_model)

    if not backend.get("api_key"):
        raise HTTPException(status_code=400, detail=f"API key not configured for model: {requested_model}")

    body["model"] = backend["model_name"]

    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {backend['api_key']}"}
    if "extra_headers" in backend:
        headers.update(backend["extra_headers"])

    messages = body.get("messages", [])
    user_msg = ""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if isinstance(content, str):
                user_msg = content
            elif isinstance(content, list):
                user_msg = " ".join(part.get("text", "") for part in content if part.get("type") == "text")
            break

    # ===== v3: 推断记忆通道 =====
    channel = get_channel_from_model(requested_model)

    # ===== v2: 场景检测 =====
    current_scene = "daily"
    try:
        current_scene = scene_detector.detect(user_msg, channel=channel)
        if scene_detector.has_scene_changed():
            print(f"[v2] Scene changed to: {current_scene} (channel={channel})")
    except Exception as e:
        print(f"[v2] Scene detection error: {e}")

    # ===== v2: 自动注入记忆 =====
    try:
        messages = await auto_inject.process(
            user_msg=user_msg,
            scene_type=current_scene,
            messages=messages,
            channel=channel
        )
        body["messages"] = messages
    except Exception as e:
        print(f"[v2] Auto-inject error: {e}")

    is_stream = body.get("stream", False)
    target_url = f"{backend['base_url']}/chat/completions"

    print(f"[{datetime.now().strftime('%H:%M:%S')}] {requested_model} -> {backend['model_name']} | stream={is_stream} | scene={current_scene} | channel={channel}")

    # 假流式模型走非流式请求再包装成SSE
    if "假流式" in requested_model:
        return await fake_stream_to_normal(target_url, headers, body, user_msg, current_scene, channel)
    elif is_stream:
        collector = {"assistant_chunks": [], "reasoning_chunks": []}
        return StreamingResponse(
            stream_chunks(target_url, headers, body, collector),
            media_type="text/event-stream",
            background=BackgroundTask(store_stream_result, collector, user_msg, current_scene, channel)
        )
    else:
        return await non_stream_request(target_url, headers, body, user_msg, current_scene, channel)

# ============ Reverie 新流程 ============

async def _reverie_chat(body: dict, session_id: str, request: Request, background_tasks: BackgroundTasks):
    """Reverie 新流程：JWT鉴权 → 上下文构建 → 通道路由 → 流式转发 → 异步存储"""

    # 1. JWT 鉴权
    from auth import verify_token
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="缺少 Authorization")
    verify_token(auth_header.replace("Bearer ", ""))

    # 2. 解析请求
    model_name = body.get("model", "deepseek-chat")
    messages = body.get("messages", [])
    stream = body.get("stream", True)
    user_input = messages[-1]["content"] if messages else ""
    model_channel, _, _ = resolve_channel(model_name)

    # 获取 session 的真实 scene_type（用于存储，避免硬编码 "daily"）
    session_scene_type = "daily"
    try:
        from config import get_supabase
        _sr = get_supabase().table("sessions").select("scene_type").eq("id", session_id).execute()
        if _sr.data:
            session_scene_type = _sr.data[0].get("scene_type") or "daily"
    except Exception as _e:
        logger.warning(f"[reverie] fetch scene_type failed: {_e}")

    # 3. 上下文构建（如果启用）
    if FEATURE_FLAGS.get("context_inject_enabled") and messages:
        try:
            context = await build_context(session_id, user_input, model_channel)
            # context 是 [{"role": "system", "content": "..."}]，插到 messages 最前面
            messages = context + messages
        except Exception as e:
            logger.warning(f"[reverie] context build failed: {e}")

    # 3.5 拉取历史对话（滑动窗口，按 token 预算截取）
    MAX_HISTORY_TOKENS = 8000
    history_messages = []
    try:
        from config import get_supabase
        history_result = get_supabase().table("conversations") \
            .select("user_msg, assistant_msg") \
            .eq("session_id", session_id) \
            .order("created_at", desc=False) \
            .limit(50) \
            .execute()
        history_rows = history_result.data or []

        all_history = []
        for row in history_rows:
            if row.get("user_msg"):
                all_history.append({"role": "user", "content": row["user_msg"]})
            if row.get("assistant_msg"):
                all_history.append({"role": "assistant", "content": row["assistant_msg"]})

        # 从末尾往前累计 token 数，超预算时截断
        used_tokens = 0
        cutoff = 0
        for i in range(len(all_history) - 1, -1, -1):
            text = all_history[i]["content"]
            chinese = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
            tokens = int(chinese / 1.5 + (len(text) - chinese) / 4)
            if used_tokens + tokens > MAX_HISTORY_TOKENS:
                cutoff = i + 1
                break
            used_tokens += tokens

        history_messages = all_history[cutoff:]
        logger.info(f"[reverie] history: {len(history_messages)} messages, trimmed to fit {MAX_HISTORY_TOKENS} tokens")
    except Exception as e:
        logger.warning(f"[reverie] history fetch failed: {e}")

    # 拼装最终 messages：context（可选）+ history + current user message
    messages = messages[:-1] + history_messages + [messages[-1]]

    # 4. 通道路由
    ch_name, ch_config, resolved_model = resolve_channel(model_name)

    # 4.5 如果模型变了，更新 session 记录
    try:
        from config import get_supabase
        session_result = get_supabase().table("sessions").select("model").eq("id", session_id).execute()
        if session_result.data:
            stored_model = session_result.data[0].get("model")
            if stored_model != model_name:
                get_supabase().table("sessions").update({
                    "model": model_name,
                    "updated_at": datetime.now(timezone.utc).isoformat()
                }).eq("id", session_id).execute()
                logger.info(f"[reverie] session model updated: {stored_model} -> {model_name}")
    except Exception as e:
        logger.warning(f"[reverie] update session model failed: {e}")

    # 5. 组装上游请求头
    headers = {
        "Authorization": f"Bearer {ch_config['api_key']}",
        "Content-Type": "application/json",
    }
    if ch_config.get("provider") == "openrouter":
        headers["HTTP-Referer"] = "https://kdreamling.work"
        headers["X-Title"] = "Reverie"

    upstream_body = {
        "model": resolved_model,
        "messages": messages,
        "stream": stream,
    }

    timeout = get_timeout(resolved_model)

    logger.info(f"[reverie] session={session_id} model={model_name} -> ch={ch_name}/{resolved_model} stream={stream}")

    if stream:
        return StreamingResponse(
            _reverie_stream(ch_name, ch_config, headers, upstream_body, session_id, user_input, timeout, background_tasks, model_channel, session_scene_type),
            media_type="text/event-stream",
        )
    else:
        proxy = get_proxy(ch_config["base_url"])
        async with httpx.AsyncClient(timeout=timeout, proxy=proxy) as client:
            resp = await client.post(
                f"{ch_config['base_url']}/chat/completions",
                headers=headers,
                json=upstream_body,
            )
            resp.raise_for_status()
            data = resp.json()

        assistant_msg = ""
        try:
            assistant_msg = data["choices"][0]["message"].get("content", "") or ""
        except Exception:
            pass

        background_tasks.add_task(_reverie_store, session_id, user_input, assistant_msg, session_scene_type, "", model_channel)
        return JSONResponse(content=data)


async def _reverie_stream(ch_name, ch_config, headers, upstream_body, session_id, user_input, timeout, background_tasks, model_channel="deepseek", scene_type="daily"):
    """Reverie 流式处理：适配器统一格式 + 收集完整回复 + 异步存储"""
    adapter = ThinkingAdapter()
    thinking_buffer = []
    text_buffer = []

    supports_thinking = ch_config.get("supports_thinking", False)
    thinking_format = ch_config.get("thinking_format")
    proxy = get_proxy(ch_config["base_url"])

    try:
        async with httpx.AsyncClient(timeout=timeout, proxy=proxy) as client:
            async with client.stream(
                "POST",
                f"{ch_config['base_url']}/chat/completions",
                headers=headers,
                json=upstream_body,
            ) as response:
                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data = line[6:]
                    if data == "[DONE]":
                        break

                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue

                    if supports_thinking and thinking_format:
                        events = adapter.adapt(chunk, thinking_format)
                        for event in events:
                            if event["type"] == "thinking_delta":
                                thinking_buffer.append(event.get("content", ""))
                            elif event["type"] == "text_delta":
                                text_buffer.append(event.get("content", ""))
                            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                    else:
                        # 不支持 thinking 的模型，直接提取 content
                        delta = chunk.get("choices", [{}])[0].get("delta", {})
                        content = delta.get("content")
                        if content:
                            text_buffer.append(content)
                            yield f'data: {{"type":"text_delta","content":{json.dumps(content, ensure_ascii=False)}}}\n\n'

        yield f'data: {{"type":"done"}}\n\n'

    except Exception as e:
        logger.error(f"[reverie] stream error: {e}")
        yield f'data: {{"type":"error","content":"{str(e)}"}}\n\n'

    # 流结束后触发异步存储
    assistant_msg = "".join(text_buffer)
    if assistant_msg or thinking_buffer:
        background_tasks.add_task(
            _reverie_store, session_id, user_input, assistant_msg, scene_type, "".join(thinking_buffer), model_channel
        )


async def _reverie_store(session_id: str, user_msg: str, assistant_msg: str, scene_type: str, thinking: str = "", model_channel: str = "deepseek"):
    """Reverie 消息存储 + 微摘要触发"""
    try:
        from config import get_supabase
        sb = get_supabase()

        from datetime import timezone as _tz
        now_str = datetime.now(_tz.utc).isoformat()

        record = {
            "session_id": session_id,
            "user_id": "dream",
            "user_msg": user_msg,
            "assistant_msg": assistant_msg,
            "scene_type": scene_type,
            "model_channel": model_channel,
            "thinking_summary": thinking[:500] if thinking else None,
            "created_at": now_str,
        }

        sb.table("conversations").insert(record).execute()

        # 更新 session 统计
        await update_session_stats(session_id)

        # 触发微摘要
        if FEATURE_FLAGS.get("micro_summary_enabled") and user_msg and assistant_msg:
            try:
                await realtime_micro_summary(user_msg, assistant_msg, scene_type)
            except Exception as e:
                logger.warning(f"[reverie] micro_summary failed: {e}")

    except Exception as e:
        logger.error(f"[reverie] store failed: {e}")


# ============ 假流式处理 ============

async def fake_stream_to_normal(url: str, headers: dict, body: dict, user_msg: str, scene_type: str = "daily", channel: str = "deepseek"):
    """
    假流式：
    1. 去掉模型名前缀，以非流式方式请求
    2. 解析 content + reasoning_content + tool_calls
    3. 包装成标准SSE流返回给Kelivo（先发思考再发回答）
    4. 存储到数据库（带scene_type）
    """
    body["stream"] = False
    if isinstance(body.get("model"), str):
        body["model"] = body["model"].replace("假流式/", "", 1).replace("流式抗截断/", "", 1)

    print(f"[FakeStream] Requesting non-stream: {body['model']}")

    proxy = get_proxy(url)
    timeout = get_timeout(body.get("model", ""))

    try:
        async with httpx.AsyncClient(timeout=timeout, proxy=proxy) as client:
            response = await client.post(url, headers=headers, json=body)
            if response.status_code != 200:
                error_text = response.text
                print(f"[FakeStream] Backend error {response.status_code}: {error_text[:300]}")
                return JSONResponse(
                    status_code=response.status_code,
                    content={"error": {"message": error_text, "code": response.status_code}}
                )
            result = response.json()
    except httpx.TimeoutException:
        print(f"[FakeStream] Request timeout ({timeout}s)")
        return JSONResponse(status_code=504, content={"error": {"message": "Gateway timeout", "code": 504}})
    except Exception as e:
        print(f"[FakeStream] Connection error: {e}")
        return JSONResponse(status_code=502, content={"error": {"message": str(e), "code": 502}})

    # 解析响应
    choice = result.get("choices", [{}])[0] if result.get("choices") else {}
    message = choice.get("message", {})
    assistant_content = message.get("content", "") or ""
    reasoning_content = message.get("reasoning_content", "") or ""
    tool_calls = message.get("tool_calls")
    model_name = result.get("model", "")
    msg_id = result.get("id", f"chatcmpl-fake-{int(datetime.now().timestamp())}")
    finish_reason = choice.get("finish_reason", "stop")

    if tool_calls:
        print(f"[FakeStream] Got {len(tool_calls)} tool_calls: {[tc.get('function', {}).get('name', '?') for tc in tool_calls]}")
    if reasoning_content:
        print(f"[FakeStream] Got reasoning: {len(reasoning_content)} chars")
    if assistant_content:
        print(f"[FakeStream] Got content: {len(assistant_content)} chars")
    if not assistant_content and not reasoning_content and not tool_calls:
        print(f"[FakeStream] WARNING: Empty response! Full result: {json.dumps(result, ensure_ascii=False)[:500]}")

    # 存储到数据库（v3: 带scene_type + channel，使用pgvector）
    storage_text = assistant_content or reasoning_content
    if user_msg and storage_text and not should_skip_storage(user_msg):
        try:
            conv_id = await save_conversation_with_round(user_msg, storage_text, scene_type=scene_type, channel=channel)
            asyncio.create_task(check_and_generate_summary(channel=channel))
            if conv_id:
                asyncio.create_task(store_conversation_embedding(conv_id, user_msg, storage_text))
            print(f"[FakeStream] Saved to DB (scene={scene_type}, channel={channel})")
        except Exception as e:
            print(f"[FakeStream] Storage error: {e}")

    # 包装成标准SSE流返回给Kelivo
    async def generate_sse():
        created = int(datetime.now().timestamp())

        if tool_calls:
            # ===== 工具调用模式 =====
            # 先发送思考过程（如果有）
            if reasoning_content:
                chunk_size = 4
                for i in range(0, len(reasoning_content), chunk_size):
                    text_chunk = reasoning_content[i:i + chunk_size]
                    chunk_data = {
                        "id": msg_id,
                        "object": "chat.completion.chunk",
                        "created": created,
                        "model": model_name,
                        "choices": [{
                            "index": 0,
                            "delta": {"reasoning_content": text_chunk},
                            "finish_reason": None
                        }]
                    }
                    yield f"data: {json.dumps(chunk_data, ensure_ascii=False)}\n\n".encode()
                    await asyncio.sleep(0.02)

            for tc_idx, tc in enumerate(tool_calls):
                func = tc.get("function", {})
                tc_id = tc.get("id", f"call_{tc_idx}")
                arguments = func.get("arguments", "")

                first_delta = {
                    "tool_calls": [{
                        "index": tc_idx,
                        "id": tc_id,
                        "type": "function",
                        "function": {
                            "name": func.get("name", ""),
                            "arguments": ""
                        }
                    }]
                }
                if tc_idx == 0:
                    first_delta["role"] = "assistant"
                    first_delta["content"] = None

                yield f"data: {json.dumps({'id': msg_id, 'object': 'chat.completion.chunk', 'created': created, 'model': model_name, 'choices': [{'index': 0, 'delta': first_delta, 'finish_reason': None}]}, ensure_ascii=False)}\n\n".encode()

                if arguments:
                    arg_delta = {
                        "tool_calls": [{
                            "index": tc_idx,
                            "function": {"arguments": arguments}
                        }]
                    }
                    yield f"data: {json.dumps({'id': msg_id, 'object': 'chat.completion.chunk', 'created': created, 'model': model_name, 'choices': [{'index': 0, 'delta': arg_delta, 'finish_reason': None}]}, ensure_ascii=False)}\n\n".encode()

            yield f"data: {json.dumps({'id': msg_id, 'object': 'chat.completion.chunk', 'created': created, 'model': model_name, 'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'tool_calls'}]}, ensure_ascii=False)}\n\n".encode()
            yield b"data: [DONE]\n\n"

        else:
            # ===== 文本模式（含思考过程） =====
            # 第一个chunk带role
            first_chunk = {
                "id": msg_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model_name,
                "choices": [{
                    "index": 0,
                    "delta": {"role": "assistant", "content": ""},
                    "finish_reason": None
                }]
            }
            yield f"data: {json.dumps(first_chunk, ensure_ascii=False)}\n\n".encode()

            # 先发送 reasoning_content（思考过程）
            if reasoning_content:
                chunk_size = 4
                for i in range(0, len(reasoning_content), chunk_size):
                    text_chunk = reasoning_content[i:i + chunk_size]
                    chunk_data = {
                        "id": msg_id,
                        "object": "chat.completion.chunk",
                        "created": created,
                        "model": model_name,
                        "choices": [{
                            "index": 0,
                            "delta": {"reasoning_content": text_chunk},
                            "finish_reason": None
                        }]
                    }
                    yield f"data: {json.dumps(chunk_data, ensure_ascii=False)}\n\n".encode()
                    await asyncio.sleep(0.02)

            # 再发送 content（最终回答）
            if assistant_content:
                chunk_size = 4
                for i in range(0, len(assistant_content), chunk_size):
                    text_chunk = assistant_content[i:i + chunk_size]
                    chunk_data = {
                        "id": msg_id,
                        "object": "chat.completion.chunk",
                        "created": created,
                        "model": model_name,
                        "choices": [{
                            "index": 0,
                            "delta": {"content": text_chunk},
                            "finish_reason": None
                        }]
                    }
                    yield f"data: {json.dumps(chunk_data, ensure_ascii=False)}\n\n".encode()
                    await asyncio.sleep(0.02)

            # 结束标记
            yield f"data: {json.dumps({'id': msg_id, 'object': 'chat.completion.chunk', 'created': created, 'model': model_name, 'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}]}, ensure_ascii=False)}\n\n".encode()
            yield b"data: [DONE]\n\n"

    return StreamingResponse(generate_sse(), media_type="text/event-stream")

# ============ 正常流式处理 ============

async def stream_chunks(url: str, headers: dict, body: dict, collector: dict) -> AsyncGenerator[bytes, None]:
    """流式转发响应给客户端，同时收集 chunks 到 collector 字典。
    存储逻辑由 BackgroundTask(store_stream_result) 在响应结束后独立执行，
    避免客户端断连导致 async generator 被取消而丢失存储。"""
    proxy = get_proxy(url)
    timeout = get_timeout(body.get("model", ""))

    try:
        async with httpx.AsyncClient(timeout=timeout, proxy=proxy) as client:
            async with client.stream("POST", url, headers=headers, json=body) as response:
                if response.status_code != 200:
                    error_body = await response.aread()
                    print(f"[Stream] Backend error {response.status_code}: {error_body.decode()[:300]}")
                    yield f"data: {json.dumps({'error': error_body.decode()})}\n\n".encode()
                    collector["error"] = True
                    return
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        yield f"{line}\n\n".encode()
                        if line == "data: [DONE]":
                            continue
                        try:
                            data = json.loads(line[6:])
                            delta = data.get("choices", [{}])[0].get("delta", {})
                            content = delta.get("content", "")
                            reasoning = delta.get("reasoning_content", "")
                            if content:
                                collector["assistant_chunks"].append(content)
                            if reasoning:
                                collector["reasoning_chunks"].append(reasoning)
                        except:
                            pass
    except Exception as e:
        print(f"[Stream] Connection error: {e}")
        collector["error"] = True


async def store_stream_result(collector: dict, user_msg: str, scene_type: str, channel: str):
    """BackgroundTask：在流式响应完全结束后执行，将收集到的内容存入数据库。
    此函数独立于 StreamingResponse 运行，不受客户端断连影响。"""
    if collector.get("error"):
        print(f"[Stream] Storage skipped due to stream error")
        return

    assistant_chunks = collector.get("assistant_chunks", [])
    reasoning_chunks = collector.get("reasoning_chunks", [])
    assistant_msg = "".join(assistant_chunks)
    reasoning_msg = "".join(reasoning_chunks)

    print(f"[Stream] Chunks collected: content={len(assistant_chunks)}, reasoning={len(reasoning_chunks)}, user_msg_len={len(user_msg)}, skip={should_skip_storage(user_msg) if user_msg else 'no_user_msg'}")

    storage_text = assistant_msg or reasoning_msg
    if user_msg and storage_text and not should_skip_storage(user_msg):
        try:
            conv_id = await save_conversation_with_round(user_msg, storage_text, scene_type=scene_type, channel=channel)
            asyncio.create_task(check_and_generate_summary(channel=channel))
            if conv_id:
                asyncio.create_task(store_conversation_embedding(conv_id, user_msg, storage_text))
            print(f"[Stream] Saved to DB (scene={scene_type}, channel={channel})")
        except Exception as e:
            print(f"[Stream] Storage error: {e}")
    else:
        print(f"[Stream] Storage SKIPPED: user_msg={bool(user_msg)}, storage_text={bool(storage_text)}, content_len={len(assistant_msg)}, reasoning_len={len(reasoning_msg)}")

# ============ 非流式处理 ============

async def non_stream_request(url: str, headers: dict, body: dict, user_msg: str, scene_type: str = "daily", channel: str = "deepseek") -> JSONResponse:
    proxy = get_proxy(url)
    timeout = get_timeout(body.get("model", ""))

    try:
        async with httpx.AsyncClient(timeout=timeout, proxy=proxy) as client:
            response = await client.post(url, headers=headers, json=body)
    except httpx.TimeoutException:
        print(f"[NonStream] Request timeout ({timeout}s)")
        return JSONResponse(status_code=504, content={"error": "Gateway timeout"})
    except Exception as e:
        print(f"[NonStream] Connection error: {e}")
        return JSONResponse(status_code=502, content={"error": str(e)})

    if response.status_code != 200:
        print(f"[NonStream] Backend error {response.status_code}: {response.text[:300]}")
        return JSONResponse(status_code=response.status_code, content={"error": response.text})

    result = response.json()

    # 提取content和reasoning_content
    assistant_msg = ""
    reasoning_msg = ""
    try:
        message = result["choices"][0]["message"]
        assistant_msg = message.get("content", "") or ""
        reasoning_msg = message.get("reasoning_content", "") or ""
    except:
        pass

    if not assistant_msg and not reasoning_msg:
        print(f"[NonStream] WARNING: Empty response! Full result: {json.dumps(result, ensure_ascii=False)[:500]}")

    # 存储（v3: 带scene_type + channel，使用pgvector）
    storage_text = assistant_msg or reasoning_msg
    if user_msg and storage_text and not should_skip_storage(user_msg):
        try:
            conv_id = await save_conversation_with_round(user_msg, storage_text, scene_type=scene_type, channel=channel)
            asyncio.create_task(check_and_generate_summary(channel=channel))
            if conv_id:
                asyncio.create_task(store_conversation_embedding(conv_id, user_msg, storage_text))
        except Exception as e:
            print(f"[NonStream] Storage error: {e}")

    return JSONResponse(content=result)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)

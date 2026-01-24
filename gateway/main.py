"""
Memory Gateway - 多后端代理网关
支持 DeepSeek、OpenRouter（GPT-4o、Claude等）统一转发
"""

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from contextlib import asynccontextmanager
import httpx
import json
import asyncio
from typing import AsyncGenerator, Optional
from datetime import datetime

import sys
sys.path.insert(0, '/home/dream/memory-system/gateway')
from config import get_settings
from services.storage import save_conversation
from services.background import sync_service
from routers.mcp_tools import router as mcp_router

settings = get_settings()

# ============ 多后端配置 ============

BACKENDS = {
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
    "deepseek-coder": {
        "base_url": "https://api.deepseek.com/v1",
        "api_key": settings.llm_api_key,
        "model_name": "deepseek-coder"
    },
    
    # OpenRouter 模型 (GPT-4o, Claude, etc.)
    # 在 .env 中设置 OPENROUTER_API_KEY
    "gpt-4o": {
        "base_url": "https://openrouter.ai/api/v1",
        "api_key": settings.openrouter_api_key,
        "model_name": "openai/gpt-4o",
        "extra_headers": {
            "HTTP-Referer": "https://memory-system.local",
            "X-Title": "Memory Gateway"
        }
    },
    "gpt-4o-mini": {
        "base_url": "https://openrouter.ai/api/v1",
        "api_key": settings.openrouter_api_key,
        "model_name": "openai/gpt-4o-mini",
        "extra_headers": {
            "HTTP-Referer": "https://memory-system.local",
            "X-Title": "Memory Gateway"
        }
    },
    "claude-3.5-sonnet": {
        "base_url": "https://openrouter.ai/api/v1",
        "api_key": settings.openrouter_api_key,
        "model_name": "anthropic/claude-3.5-sonnet",
        "extra_headers": {
            "HTTP-Referer": "https://memory-system.local",
            "X-Title": "Memory Gateway"
        }
    },
    "claude-3-opus": {
        "base_url": "https://openrouter.ai/api/v1",
        "api_key": settings.openrouter_api_key,
        "model_name": "anthropic/claude-3-opus",
        "extra_headers": {
            "HTTP-Referer": "https://memory-system.local",
            "X-Title": "Memory Gateway"
        }
    },
}

# 模型别名映射（用户可以用简短名称）
MODEL_ALIASES = {
    "gpt-4o": "gpt-4o",
    "4o": "gpt-4o",
    "gpt-4o-mini": "gpt-4o-mini",
    "4o-mini": "gpt-4o-mini",
    "claude": "claude-3.5-sonnet",
    "claude-sonnet": "claude-3.5-sonnet",
    "claude-opus": "claude-3-opus",
    "deepseek": "deepseek-chat",
    "deepseek-chat": "deepseek-chat",
    "deepseek-coder": "deepseek-coder",
    "deepseek-reasoner": "deepseek-reasoner",
}

# ============ 过滤关键词 ============

SYSTEM_KEYWORDS = [
    "<content>", "summarize", "summary", "总结", "标题", "title",
    "I will give you", "system_auto", "health_check",
    "你是一个", "You are a", "As an AI", "作为AI",
    "Generate a concise", "Based on the conversation"
]

def should_skip_storage(user_msg: str) -> bool:
    """判断是否应该跳过存储（系统消息过滤）"""
    if not user_msg or len(user_msg.strip()) < 2:
        return True
    for kw in SYSTEM_KEYWORDS:
        if kw.lower() in user_msg.lower():
            return True
    return False

def get_backend_config(model: str) -> dict:
    """根据模型名获取后端配置"""
    # 先检查别名
    resolved_model = MODEL_ALIASES.get(model.lower(), model)
    
    # 直接匹配
    if resolved_model in BACKENDS:
        return BACKENDS[resolved_model]
    
    # OpenRouter模型（带/的格式如 openai/gpt-4o）
    if "/" in model:
        return {
            "base_url": "https://openrouter.ai/api/v1",
            "api_key": settings.openrouter_api_key,
            "model_name": model,
            "extra_headers": {
                "HTTP-Referer": "https://memory-system.local",
                "X-Title": "Memory Gateway"
            }
        }
    
    # 默认使用DeepSeek
    print(f"Unknown model '{model}', falling back to deepseek-chat")
    return BACKENDS["deepseek-chat"]

# ============ 生命周期管理 ============

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    print("Starting Memory Gateway...")
    print(f"Supported models: {list(BACKENDS.keys())}")
    print(f"Model aliases: {list(MODEL_ALIASES.keys())}")
    
    # 启动后台同步服务
    try:
        await sync_service.start()
    except Exception as e:
        print(f"Warning: Background sync service failed to start: {e}")
    
    yield
    
    # 关闭后台服务
    try:
        await sync_service.stop()
    except:
        pass
    print("Gateway shutdown complete")

app = FastAPI(title="Memory Gateway", lifespan=lifespan)

# 注册MCP路由
app.include_router(mcp_router)

# ============ 健康检查 ============

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "supported_models": list(BACKENDS.keys()),
        "aliases": list(MODEL_ALIASES.keys())
    }

@app.get("/models")
async def list_models():
    """列出支持的模型"""
    return {
        "models": list(BACKENDS.keys()),
        "aliases": MODEL_ALIASES
    }

# ============ 核心代理逻辑 ============

@app.post("/v1/chat/completions")
async def proxy_chat_completions(request: Request):
    """代理聊天请求到对应后端"""
    
    try:
        body = await request.json()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {e}")
    
    # 获取模型和后端配置
    requested_model = body.get("model", "deepseek-chat")
    backend = get_backend_config(requested_model)
    
    if not backend.get("api_key"):
        raise HTTPException(
            status_code=400, 
            detail=f"API key not configured for model: {requested_model}. Check your .env file."
        )
    
    # 修改请求中的模型名为后端实际模型名
    body["model"] = backend["model_name"]
    
    # 构建headers
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {backend['api_key']}"
    }
    # 添加额外headers（如OpenRouter需要的）
    if "extra_headers" in backend:
        headers.update(backend["extra_headers"])
    
    # 提取用户消息用于存储
    messages = body.get("messages", [])
    user_msg = ""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if isinstance(content, str):
                user_msg = content
            elif isinstance(content, list):
                # 处理多模态消息
                user_msg = " ".join(
                    part.get("text", "") for part in content 
                    if part.get("type") == "text"
                )
            break
    
    is_stream = body.get("stream", False)
    target_url = f"{backend['base_url']}/chat/completions"
    
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {requested_model} -> {backend['model_name']} | stream={is_stream}")
    
    if is_stream:
        return StreamingResponse(
            stream_and_store(target_url, headers, body, user_msg),
            media_type="text/event-stream"
        )
    else:
        return await non_stream_request(target_url, headers, body, user_msg)


async def stream_and_store(
    url: str, 
    headers: dict, 
    body: dict, 
    user_msg: str
) -> AsyncGenerator[bytes, None]:
    """流式请求并存储对话"""
    
    assistant_chunks = []
    
    proxy = settings.proxy_url if settings.proxy_url else None
    async with httpx.AsyncClient(timeout=120.0, proxy=proxy) as client:
        async with client.stream("POST", url, headers=headers, json=body) as response:
            if response.status_code != 200:
                error_body = await response.aread()
                yield f"data: {json.dumps({'error': error_body.decode()})}\n\n".encode()
                return
            
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    yield f"{line}\n\n".encode()
                    
                    # 提取内容
                    if line == "data: [DONE]":
                        continue
                    try:
                        data = json.loads(line[6:])
                        delta = data.get("choices", [{}])[0].get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            assistant_chunks.append(content)
                    except:
                        pass
    
    # 存储对话
    assistant_msg = "".join(assistant_chunks)
    if user_msg and assistant_msg and not should_skip_storage(user_msg):
        try:
            await save_conversation(user_msg, assistant_msg)
        except Exception as e:
            print(f"Storage error: {e}")


async def non_stream_request(
    url: str, 
    headers: dict, 
    body: dict, 
    user_msg: str
) -> JSONResponse:
    """非流式请求"""
    
    proxy = settings.proxy_url if settings.proxy_url else None
    async with httpx.AsyncClient(timeout=120.0, proxy=proxy) as client:
        response = await client.post(url, headers=headers, json=body)
        
        if response.status_code != 200:
            return JSONResponse(
                status_code=response.status_code,
                content={"error": response.text}
            )
        
        result = response.json()
        
        # 提取助手回复
        assistant_msg = ""
        try:
            assistant_msg = result["choices"][0]["message"]["content"]
        except:
            pass
        
        # 存储对话
        if user_msg and assistant_msg and not should_skip_storage(user_msg):
            try:
                await save_conversation(user_msg, assistant_msg)
            except Exception as e:
                print(f"Storage error: {e}")
        
        return JSONResponse(content=result)


# ============ 启动入口 ============

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)

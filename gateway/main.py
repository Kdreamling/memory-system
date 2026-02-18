"""
Memory Gateway - 多后端代理网关
支持 DeepSeek、OpenRouter（GPT-4o、Claude、Gemini等）统一转发
v2.1 - 修复reasoning_content丢失、空回（不使用全局连接池）
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
from services.storage import save_conversation_with_round, update_weight
from services.summary_service import check_and_generate_summary
from services.embedding_service import store_conversation_embedding
import re
# from services.background import sync_service
from routers.mcp_tools import router as mcp_router

settings = get_settings()

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
    "deepseek": "deepseek-chat",
    "deepseek-chat": "deepseek-chat",
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
    print("Starting Memory Gateway v2.1...")
    print(f"Supported models: {list(BACKENDS.keys())}")
    try:
        pass  # await sync_service.start()
    except Exception as e:
        print(f"Warning: Background sync service failed to start: {e}")
    yield
    try:
        pass  # await sync_service.stop()
    except:
        pass
    print("Gateway shutdown complete")

app = FastAPI(title="Memory Gateway", lifespan=lifespan)
app.include_router(mcp_router)

@app.get("/health")
async def health_check():
    return {"status": "healthy", "version": "2.1", "timestamp": datetime.now().isoformat(), "supported_models": list(BACKENDS.keys())}

@app.get("/models")
async def list_models():
    return {"models": list(BACKENDS.keys()), "aliases": MODEL_ALIASES}

@app.post("/v1/chat/completions")
async def proxy_chat_completions(request: Request):
    try:
        body = await request.json()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {e}")
    
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
    
    is_stream = body.get("stream", False)
    target_url = f"{backend['base_url']}/chat/completions"
    
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {requested_model} -> {backend['model_name']} | stream={is_stream}")
    
    # 假流式模型走非流式请求再包装成SSE
    if "假流式" in requested_model:
        return await fake_stream_to_normal(target_url, headers, body, user_msg)
    elif is_stream:
        return StreamingResponse(stream_and_store(target_url, headers, body, user_msg), media_type="text/event-stream")
    else:
        return await non_stream_request(target_url, headers, body, user_msg)

# ============ 假流式处理 ============

async def fake_stream_to_normal(url: str, headers: dict, body: dict, user_msg: str):
    """
    假流式：
    1. 去掉模型名前缀，以非流式方式请求
    2. 解析 content + reasoning_content + tool_calls
    3. 包装成标准SSE流返回给Kelivo（先发思考再发回答）
    4. 存储到数据库
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
    
    # 存储到数据库（优先存content，content为空则存reasoning）
    storage_text = assistant_content or reasoning_content
    if user_msg and storage_text and not should_skip_storage(user_msg):
        try:
            conv_id = await save_conversation_with_round(user_msg, storage_text)
            asyncio.create_task(check_and_generate_summary())
            if conv_id:
                asyncio.create_task(store_conversation_embedding(conv_id, user_msg, storage_text))
            print(f"[FakeStream] Saved to DB")
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

async def stream_and_store(url: str, headers: dict, body: dict, user_msg: str) -> AsyncGenerator[bytes, None]:
    assistant_chunks = []
    reasoning_chunks = []
    proxy = get_proxy(url)
    timeout = get_timeout(body.get("model", ""))
    
    async with httpx.AsyncClient(timeout=timeout, proxy=proxy) as client:
        async with client.stream("POST", url, headers=headers, json=body) as response:
            if response.status_code != 200:
                error_body = await response.aread()
                print(f"[Stream] Backend error {response.status_code}: {error_body.decode()[:300]}")
                yield f"data: {json.dumps({'error': error_body.decode()})}\n\n".encode()
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
                            assistant_chunks.append(content)
                        if reasoning:
                            reasoning_chunks.append(reasoning)
                    except:
                        pass
    
    assistant_msg = "".join(assistant_chunks)
    reasoning_msg = "".join(reasoning_chunks)
    
    # 存储：优先存content，content为空则存reasoning
    storage_text = assistant_msg or reasoning_msg
    if user_msg and storage_text and not should_skip_storage(user_msg):
        try:
            conv_id = await save_conversation_with_round(user_msg, storage_text)
            asyncio.create_task(check_and_generate_summary())
            if conv_id:
                asyncio.create_task(store_conversation_embedding(conv_id, user_msg, storage_text))
        except Exception as e:
            print(f"[Stream] Storage error: {e}")

# ============ 非流式处理 ============

async def non_stream_request(url: str, headers: dict, body: dict, user_msg: str) -> JSONResponse:
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
    
    # 存储：优先存content，content为空则存reasoning
    storage_text = assistant_msg or reasoning_msg
    if user_msg and storage_text and not should_skip_storage(user_msg):
        try:
            conv_id = await save_conversation_with_round(user_msg, storage_text)
            asyncio.create_task(check_and_generate_summary())
            if conv_id:
                asyncio.create_task(store_conversation_embedding(conv_id, user_msg, storage_text))
        except Exception as e:
            print(f"[NonStream] Storage error: {e}")
    
    return JSONResponse(content=result)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)

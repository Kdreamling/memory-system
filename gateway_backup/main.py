from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
import httpx
import json
import sys
sys.path.insert(0, '/home/dream/memory-system/gateway')
from config import get_settings
from services.storage import save_conversation
from routers.mcp_tools import router as mcp_router

app = FastAPI(title="Memory Gateway")
settings = get_settings()
app.include_router(mcp_router)

# 系统消息过滤关键词
SYSTEM_KEYWORDS = [
    "<content>",
    "summarize",
    "summary", 
    "总结",
    "标题",
    "title",
    "I will give you",
    "system_auto",
    "health_check",
    "你是一个",
    "You are a",
    "As an AI",
    "作为AI",
]

def is_system_message(msg: str) -> bool:
    """判断是否为系统消息"""
    if not msg:
        return True
    msg_lower = msg.lower()
    for kw in SYSTEM_KEYWORDS:
        if kw.lower() in msg_lower:
            return True
    # 过滤太短的消息
    if len(msg.strip()) < 2:
        return True
    return False

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.post("/v1/chat/completions")
async def proxy_chat(request: Request):
    try:
        body = await request.json()
        messages = body.get("messages", [])
        stream = body.get("stream", False)
        
        # 调试日志
        print("\n" + "="*50)
        print("收到请求，messages数量:", len(messages))
        for i, msg in enumerate(messages):
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            preview = content[:100] if isinstance(content, str) else str(content)[:100]
            print(f"  [{i}] {role}: {preview}...")
        print("="*50 + "\n")
        
        # 获取用户最后一条消息（跳过系统消息）
        user_msg = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                content = msg.get("content", "")
                if not is_system_message(content):
                    user_msg = content
                    break
        
        # 转发到DeepSeek
        headers = {
            "Authorization": f"Bearer {settings.llm_api_key}",
            "Content-Type": "application/json"
        }
        
        if stream:
            return await handle_stream(body, headers, user_msg)
        else:
            return await handle_normal(body, headers, user_msg)
            
    except Exception as e:
        print(f"proxy error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

async def handle_normal(body: dict, headers: dict, user_msg: str):
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            f"{settings.llm_base_url}/chat/completions",
            headers=headers,
            json=body
        )
        
        result = response.json()
        
        # 提取助手回复并保存
        if "choices" in result and len(result["choices"]) > 0:
            assistant_msg = result["choices"][0].get("message", {}).get("content", "")
            if user_msg and assistant_msg and not is_system_message(assistant_msg):
                await save_conversation(user_msg, assistant_msg)
                print(f"已保存对话: {user_msg[:50]}...")
        
        return JSONResponse(content=result)

async def handle_stream(body: dict, headers: dict, user_msg: str):
    collected_content = []
    
    async def generate():
        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream(
                "POST",
                f"{settings.llm_base_url}/chat/completions",
                headers=headers,
                json=body
            ) as response:
                async for chunk in response.aiter_text():
                    yield chunk
                    
                    # 收集内容用于保存
                    for line in chunk.split("\n"):
                        if line.startswith("data: ") and not line.startswith("data: [DONE]"):
                            try:
                                data = json.loads(line[6:])
                                delta = data.get("choices", [{}])[0].get("delta", {})
                                if "content" in delta and delta["content"]:
                                    collected_content.append(delta["content"])
                            except:
                                pass
        
        # 流结束后保存对话
        assistant_msg = "".join(collected_content)
        if user_msg and assistant_msg and not is_system_message(assistant_msg):
            await save_conversation(user_msg, assistant_msg)
            print(f"[Stream] 已保存对话: {user_msg[:50]}...")
    
    return StreamingResponse(generate(), media_type="text/event-stream")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=settings.gateway_port)

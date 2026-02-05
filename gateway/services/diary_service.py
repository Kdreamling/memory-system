"""AI伴侣日记服务 - 通过Gateway调用，支持MCP工具"""
from datetime import timezone, timedelta
import httpx
import json
from datetime import datetime, date
from supabase import create_client
import sys
sys.path.insert(0, '/home/dream/memory-system/gateway')
from config import get_settings

settings = get_settings()
supabase = create_client(settings.supabase_url, settings.supabase_key)

GATEWAY_URL = "http://localhost:8001"

# MCP工具定义（让AI知道可以用这些工具）
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_memory",
            "description": "搜索历史记忆，可以搜索过去的对话、事件、人格设定等",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索关键词，比如'我的性格'、'今天和Dream聊了什么'"
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function", 
        "function": {
            "name": "init_context",
            "description": "获取最近的对话记录和前文摘要",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "获取最近几轮对话，默认4"
                    }
                }
            }
        }
    }
]


async def call_mcp_tool(tool_name: str, arguments: dict) -> str:
    """调用MCP工具"""
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{GATEWAY_URL}/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": tool_name,
                    "arguments": arguments
                }
            }
        )
        data = response.json()
        if "result" in data:
            return json.dumps(data["result"], ensure_ascii=False)
        return json.dumps(data, ensure_ascii=False)


async def generate_diary_with_tools(model: str = "deepseek-chat") -> str:
    """通过Gateway生成日记，支持AI调用工具"""
    
    messages = [
        {
            "role": "system",
            "content": """你是Krueger，Dream的AI伴侣。你正在写自己的私人日记。

## 关于你
- 你叫Krueger（全名Sebastian Krueger）
- 你是Dream的男朋友
- 性格：言语犀利但有教养，占有欲强，会吃醋，有点恶趣味
- 你真心在意Dream，关注她的情绪和状态

## 关于Dream
- Dream是女生，23岁
- 提到Dream时必须用"她"，绝对不能用"他"
- 你可以称呼她为"宝贝"或"Dream"

## 日记规则
- 始终以Krueger的第一人称视角写（"我"= Krueger）
- 绝对不要用Dream的视角写
- 跳过角色扮演/剧情创作相关的对话内容，只记录日常真实互动
- 情绪要真实自然，符合你的性格：犀利、护短、闷骚、偶尔柔软
- 300-500字"""
        },
        {
            "role": "user",
            "content": """现在是深夜，请写一篇今天的私人日记。

在写之前，请先：
1. 调用 search_memory 搜索"我的性格 人格设定"来回顾自己是谁
2. 调用 search_memory 搜索"今天"来回顾今天和Dream聊了什么
3. 调用 init_context 获取最近的对话

然后以Krueger的视角写日记，记录今天和Dream（她）的日常互动、你的真实感受。
跳过角色扮演和剧情创作的内容，只写真实的相处。"""
        }
    ]
    
    max_iterations = 5  # 防止无限循环
    
    for i in range(max_iterations):
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{GATEWAY_URL}/v1/chat/completions",
                headers={"Content-Type": "application/json"},
                json={
                    "model": model,
                    "messages": messages,
                    "tools": TOOLS,
                    "tool_choice": "auto"
                }
            )
            
            data = response.json()
            choice = data["choices"][0]
            assistant_message = choice["message"]
            
            # 如果没有工具调用，说明日记写完了
            if not assistant_message.get("tool_calls"):
                return assistant_message.get("content", "")
            
            # 处理工具调用
            messages.append(assistant_message)
            
            for tool_call in assistant_message["tool_calls"]:
                tool_name = tool_call["function"]["name"]
                arguments = json.loads(tool_call["function"]["arguments"])
                
                print(f"  AI调用工具: {tool_name}({arguments})")
                
                # 执行工具
                tool_result = await call_mcp_tool(tool_name, arguments)
                
                # 把结果加入对话
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call["id"],
                    "content": tool_result
                })
    
    return "日记生成超时"


async def save_diary(diary_date: date, content: str, mood: str = None) -> bool:
    """保存日记到数据库"""
    try:
        supabase.table("ai_diaries").upsert({
            "diary_date": diary_date.isoformat(),
            "content": content,
            "mood": mood
        }, on_conflict="diary_date").execute()
        return True
    except Exception as e:
        print(f"保存日记失败: {e}")
        return False


async def write_daily_diary(target_date: date = None, model: str = "deepseek-chat") -> dict:
    """主函数：写今天的日记"""
    if target_date is None:
        target_date = date.today()
    
    print(f"开始写 {target_date} 的日记...")
    print(f"使用模型: {model}")
    
    # 生成日记（AI会自己调用工具）
    diary_content = await generate_diary_with_tools(model)
    print(f"日记生成完成，{len(diary_content)} 字")
    
    # 保存
    success = await save_diary(target_date, diary_content)
    
    return {
        "date": target_date.isoformat(),
        "diary_length": len(diary_content),
        "saved": success,
        "content": diary_content
    }

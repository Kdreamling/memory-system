"""
MCP 工具路由 - 支持MemU语义搜索
兼容 JSON-RPC 2.0 协议
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from datetime import datetime
from typing import Any, Dict, List
import sys

sys.path.insert(0, '/home/dream/memory-system/gateway')
from services.storage import get_recent_conversations, search_conversations, get_recent_summaries
from services.memu_client import retrieve, is_available

router = APIRouter()

# ============ MCP工具定义 ============

MCP_TOOLS = [
    {
        "name": "search_memory",
        "description": "搜索与Dream的历史对话记忆。当需要回忆过去讨论过的内容、之前的约定、角色设定、剧情等时使用。支持语义搜索，能理解相关概念。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词或描述，如'Krueger的性格'、'上次约定的事情'、'之前讨论的剧情'"
                },
                "limit": {
                    "type": "integer",
                    "description": "返回结果数量",
                    "default": 5
                }
            },
            "required": []
        }
    },
    {
        "name": "init_context",
        "description": "获取最近的对话上下文。每次新对话开始时调用，用于恢复对话连续性。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "获取最近多少轮对话",
                    "default": 4
                }
            },
            "required": []
        }
    }
]

# ============ JSON-RPC 处理 ============

@router.post("/mcp")
async def handle_mcp(request: Request):
    """处理MCP JSON-RPC请求"""
    
    try:
        body = await request.json()
    except:
        return JSONResponse(content={
            "jsonrpc": "2.0",
            "id": None,
            "error": {"code": -32700, "message": "Parse error"}
        })
    
    method = body.get("method", "")
    params = body.get("params", {})
    request_id = body.get("id")
    
    print(f"[MCP] Method: {method}")
    
    # 路由到对应处理器
    handlers = {
        "initialize": handle_initialize,
        "notifications/initialized": handle_initialized,
        "tools/list": handle_tools_list,
        "tools/call": handle_tools_call,
    }
    
    handler = handlers.get(method)
    if handler:
        result = await handler(params)
        return JSONResponse(content={
            "jsonrpc": "2.0",
            "id": request_id,
            "result": result
        })
    else:
        return JSONResponse(content={
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"}
        })


async def handle_initialize(params: dict) -> dict:
    """处理初始化握手"""
    return {
        "protocolVersion": "2024-11-05",
        "capabilities": {"tools": {}},
        "serverInfo": {
            "name": "memory-gateway",
            "version": "2.0.0"
        }
    }


async def handle_initialized(params: dict) -> dict:
    """处理初始化完成通知"""
    return {}


async def handle_tools_list(params: dict) -> dict:
    """返回工具列表"""
    return {"tools": MCP_TOOLS}


async def handle_tools_call(params: dict) -> dict:
    """执行工具调用"""
    tool_name = params.get("name", "")
    arguments = params.get("arguments", {})
    
    print(f"[MCP] Tool call: {tool_name} with {arguments}")
    
    if tool_name == "search_memory":
        return await execute_search_memory(arguments)
    elif tool_name == "init_context":
        return await execute_init_context(arguments)
    else:
        return {
            "content": [{"type": "text", "text": f"Unknown tool: {tool_name}"}],
            "isError": True
        }


# ============ 工具执行逻辑 ============

async def execute_search_memory(args: dict) -> dict:
    """执行搜索记忆"""
    query = args.get("query", "")
    limit = args.get("limit", 5)
    
    if not query:
        # 没有query时返回最近对话
        recent = await get_recent_conversations("dream", limit)
        return format_conversations_result(recent, "最近的对话")
    
    # 优先使用MemU语义搜索
    if await is_available():
        print(f"[MCP] Using MemU semantic search for: {query}")
        memories = await retrieve("dream", query, limit)
        if memories:
            return format_memu_result(memories, query)
    
    # Fallback到关键词搜索
    print(f"[MCP] Falling back to keyword search for: {query}")
    results = await search_conversations(query, "dream", limit)
    return format_conversations_result(results, f"关于'{query}'的记忆")


async def execute_init_context(args: dict) -> dict:
    """执行冷启动上下文加载 - 返回摘要+最近对话"""
    limit = args.get("limit", 4)
    
    lines = []
    
    # 1. 获取最近的摘要（前文回顾）
    summaries = await get_recent_summaries("dream", 3)
    if summaries:
        lines.append("【前文回顾】以下是之前对话的摘要（仅供参考）：")
        lines.append("")
        for i, s in enumerate(reversed(summaries), 1):
            time_str = format_time(s.get("created_at", ""))
            lines.append(f"{i}. [{time_str}] {s['summary']}")
        lines.append("")
        lines.append("---")
        lines.append("")
    
    # 2. 获取最近4轮原文
    recent = await get_recent_conversations("dream", limit)
    
    if recent:
        lines.append("【最近对话】以下是最近的对话原文：")
        lines.append("")
        for conv in reversed(recent):
            time_str = format_time(conv.get("created_at", ""))
            lines.append(f"[{time_str}]")
            lines.append(f"Dream: {conv['user_msg']}")
            lines.append(f"AI: {conv['assistant_msg'][:200]}...")
            lines.append("")
    
    if not lines:
        return {
            "content": [{
                "type": "text",
                "text": "这是一个全新的对话，没有之前的对话记录。"
            }]
        }
    
    return {
        "content": [{
            "type": "text",
            "text": "\n".join(lines)
        }]
    }


# ============ 格式化辅助函数 ============

def format_conversations_result(conversations: List[Dict], title: str) -> dict:
    """格式化Supabase对话结果"""
    if not conversations:
        return {
            "content": [{
                "type": "text",
                "text": f"没有找到{title}相关的记忆。"
            }]
        }
    
    lines = [f"找到 {len(conversations)} 条{title}：", ""]
    
    for i, conv in enumerate(conversations, 1):
        time_str = format_time(conv.get("created_at", ""))
        lines.append(f"【记忆 {i}】({time_str})")
        lines.append(f"Dream: {conv['user_msg'][:150]}")
        lines.append(f"AI: {conv['assistant_msg'][:150]}")
        lines.append("")
    
    return {
        "content": [{
            "type": "text",
            "text": "\n".join(lines)
        }]
    }


def format_memu_result(memories: List[Dict], query: str) -> dict:
    """格式化MemU语义搜索结果"""
    if not memories:
        return {
            "content": [{
                "type": "text",
                "text": f"没有找到与'{query}'相关的记忆。"
            }]
        }
    
    lines = [f"找到 {len(memories)} 条与'{query}'相关的记忆（语义搜索）：", ""]
    
    for i, mem in enumerate(memories, 1):
        # MemU返回的结构可能不同，需要适配
        content = mem.get("content", mem.get("text", str(mem)))
        score = mem.get("score", mem.get("similarity", ""))
        
        lines.append(f"【记忆 {i}】")
        if score:
            lines.append(f"相关度: {score:.2f}" if isinstance(score, float) else f"相关度: {score}")
        lines.append(content[:300])
        lines.append("")
    
    return {
        "content": [{
            "type": "text",
            "text": "\n".join(lines)
        }]
    }


def format_time(time_str: str) -> str:
    """格式化时间字符串"""
    if not time_str:
        return "未知时间"
    try:
        dt = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
        return dt.strftime("%m月%d日 %H:%M")
    except:
        return time_str[:16]

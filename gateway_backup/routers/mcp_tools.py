from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
import sys
sys.path.insert(0, '/home/dream/memory-system/gateway')
from services.storage import get_recent_conversations

router = APIRouter(prefix="/mcp", tags=["MCP Tools"])

# MCP协议工具定义
MCP_TOOLS = [
    {
        "name": "search_memory",
        "description": "搜索与Dream的历史对话记忆。当需要回忆过去讨论的内容时使用。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词", "default": ""},
                "limit": {"type": "integer", "description": "返回数量", "default": 5}
            },
            "required": []
        }
    },
    {
        "name": "init_context",
        "description": "获取最近的对话上下文。每次新对话开始时调用。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "返回数量", "default": 4}
            },
            "required": []
        }
    }
]

async def handle_search_memory(args: dict) -> str:
    """处理记忆搜索"""
    query = str(args.get("query", "")) if args.get("query") else ""
    limit = int(args.get("limit", 5)) if args.get("limit") else 5
    
    conversations = await get_recent_conversations("dream", limit)
    
    # 如果有关键词，进行过滤
    if query:
        filtered = []
        for c in conversations:
            if query.lower() in c["user_msg"].lower() or query.lower() in c["assistant_msg"].lower():
                filtered.append(c)
        conversations = filtered if filtered else conversations
    
    if not conversations:
        return "没有找到相关的历史记忆。"
    
    result = f"找到{len(conversations)}条相关对话：\n"
    for i, c in enumerate(conversations):
        user_preview = c['user_msg'][:100] + "..." if len(c['user_msg']) > 100 else c['user_msg']
        assistant_preview = c['assistant_msg'][:100] + "..." if len(c['assistant_msg']) > 100 else c['assistant_msg']
        result += f"\n[{i+1}] Dream: {user_preview}\n    回复: {assistant_preview}\n"
    return result

async def handle_init_context(args: dict) -> str:
    """处理冷启动上下文加载"""
    limit = int(args.get("limit", 4)) if args.get("limit") else 4
    
    conversations = await get_recent_conversations("dream", limit)
    conversations.reverse()  # 按时间正序
    
    if not conversations:
        return "暂无历史对话记录。"
    
    result = f"最近{len(conversations)}轮对话：\n"
    for i, c in enumerate(conversations):
        user_preview = c['user_msg'][:150] + "..." if len(c['user_msg']) > 150 else c['user_msg']
        assistant_preview = c['assistant_msg'][:150] + "..." if len(c['assistant_msg']) > 150 else c['assistant_msg']
        result += f"\n[{i+1}] Dream: {user_preview}\n    回复: {assistant_preview}\n"
    return result

@router.post("")
@router.post("/")
async def mcp_handler(request: Request):
    """MCP协议主处理器 - JSON-RPC 2.0格式"""
    try:
        body = await request.json()
    except:
        return JSONResponse({"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error"}, "id": None})
    
    method = body.get("method", "")
    params = body.get("params", {})
    req_id = body.get("id", 1)
    
    print(f"[MCP] method={method}, params={params}")
    
    # 初始化握手
    if method == "initialize":
        return JSONResponse({
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "memory-mcp", "version": "1.0.0"}
            }
        })
    
    # 初始化完成通知
    if method == "notifications/initialized":
        return JSONResponse({"jsonrpc": "2.0", "id": req_id, "result": None})
    
    # 列出工具
    if method == "tools/list":
        return JSONResponse({
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"tools": MCP_TOOLS}
        })
    
    # 调用工具
    if method == "tools/call":
        tool_name = params.get("name", "")
        tool_args = params.get("arguments", {}) or {}
        
        print(f"[MCP] 调用工具: {tool_name}, 参数: {tool_args}")
        
        try:
            if tool_name == "search_memory":
                content = await handle_search_memory(tool_args)
            elif tool_name == "init_context":
                content = await handle_init_context(tool_args)
            else:
                return JSONResponse({
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"}
                })
            
            return JSONResponse({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": content}]
                }
            })
        except Exception as e:
            print(f"[MCP] 工具执行错误: {e}")
            return JSONResponse({
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32000, "message": str(e)}
            })
    
    # 未知方法
    return JSONResponse({
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"}
    })

# 保留REST接口（调试用）
@router.get("/tools")
async def list_tools():
    return {"tools": MCP_TOOLS}

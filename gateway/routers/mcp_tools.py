"""
MCP 工具路由 - Streamable HTTP MCP 协议
修复：添加 Session 管理 + SSE 端点，解决 Kelivo 掉线问题
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from datetime import datetime
from typing import Any, Dict, List
import uuid
import asyncio
import sys

sys.path.insert(0, '/home/dream/memory-system/gateway')
from services.storage import get_recent_conversations, search_conversations, get_recent_summaries
from services.memu_client import retrieve, is_available
from services.embedding_service import search_similar
from services.yuque_service import sync_diary_to_yuque
from datetime import date

router = APIRouter()

# ============ Session 管理 ============

# 存储活跃的 session（内存中即可，重启后 Kelivo 会重新 initialize）
active_sessions: Dict[str, dict] = {}


def create_session() -> str:
    """创建新 session"""
    session_id = str(uuid.uuid4())
    active_sessions[session_id] = {
        "created_at": datetime.now().isoformat(),
        "last_active": datetime.now().isoformat()
    }
    print(f"[MCP] Session created: {session_id[:8]}...")
    return session_id


def validate_session(request: Request) -> bool:
    """验证请求中的 session ID"""
    session_id = request.headers.get("mcp-session-id", "")
    if session_id and session_id in active_sessions:
        active_sessions[session_id]["last_active"] = datetime.now().isoformat()
        return True
    return False


def get_session_id(request: Request) -> str:
    """从请求头获取 session ID"""
    return request.headers.get("mcp-session-id", "")


# ============ MCP 工具定义 ============

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
    },
    {
        "name": "save_diary",
        "description": "写日记并保存到数据库和语雀。在和Dream聊天结束时，如果今天有值得记录的内容，主动写一篇日记。用第一人称写，记录今天的互动和真实感受。一天最多写2篇，超过需要询问Dream是否继续。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "日记正文（300-500字，第一人称，直接写正文不要前言）"
                },
                "mood": {
                    "type": "string",
                    "description": "今日心情，自由描述，如：开心、幸福、有点吃醋、心疼她、想她了"
                }
            },
            "required": ["content"]
        }
    }
]


# ============ JSON-RPC 请求处理（POST /mcp） ============

@router.post("/mcp")
async def handle_mcp_post(request: Request):
    """处理 MCP JSON-RPC 请求"""

    try:
        body = await request.json()
    except Exception:
        return JSONResponse(content={
            "jsonrpc": "2.0",
            "id": None,
            "error": {"code": -32700, "message": "Parse error"}
        })

    method = body.get("method", "")
    params = body.get("params", {})
    request_id = body.get("id")

    print(f"[MCP] Method: {method}")

    # initialize 不需要验证 session（因为还没有 session）
    if method == "initialize":
        result = await handle_initialize(params)
        session_id = create_session()
        response = JSONResponse(content={
            "jsonrpc": "2.0",
            "id": request_id,
            "result": result
        })
        response.headers["Mcp-Session-Id"] = session_id
        return response

    # notifications/initialized 不需要严格验证，直接通过
    if method == "notifications/initialized":
        result = await handle_initialized(params)
        response = JSONResponse(content={
            "jsonrpc": "2.0",
            "id": request_id,
            "result": result
        })
        # 保持 session header
        sid = get_session_id(request)
        if sid:
            response.headers["Mcp-Session-Id"] = sid
        return response

    # 其他方法：验证 session（宽容模式：session 无效也放行，但会 log 警告）
    sid = get_session_id(request)
    if sid and sid not in active_sessions:
        print(f"[MCP] Warning: unknown session {sid[:8]}..., allowing anyway")
        # 自动注册这个 session（兼容 Kelivo 可能的行为）
        active_sessions[sid] = {
            "created_at": datetime.now().isoformat(),
            "last_active": datetime.now().isoformat()
        }

    # 路由到对应处理器
    handlers = {
        "tools/list": handle_tools_list,
        "tools/call": handle_tools_call,
        "ping": handle_ping,
    }

    handler = handlers.get(method)
    if handler:
        result = await handler(params)
        response = JSONResponse(content={
            "jsonrpc": "2.0",
            "id": request_id,
            "result": result
        })
        if sid:
            response.headers["Mcp-Session-Id"] = sid
        return response
    else:
        response = JSONResponse(content={
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"}
        })
        if sid:
            response.headers["Mcp-Session-Id"] = sid
        return response


# ============ SSE 端点（GET /mcp）============
# Kelivo 的 Streamable HTTP 传输会用 GET 请求建立 SSE 连接
# 即使我们没有主动推送的消息，也需要保持这个连接存活

@router.get("/mcp")
async def handle_mcp_sse(request: Request):
    """SSE 端点 - 保持连接存活"""

    sid = get_session_id(request)
    if sid:
        print(f"[MCP] SSE connection opened for session {sid[:8]}...")

    async def event_stream():
        """生成 SSE 事件流，定期发送心跳保持连接"""
        try:
            while True:
                # 每 25 秒发送一个注释行作为心跳
                # SSE 规范中，以冒号开头的行是注释，客户端会忽略但连接保持活跃
                yield ": heartbeat\n\n"
                await asyncio.sleep(25)
        except asyncio.CancelledError:
            print(f"[MCP] SSE connection closed for session {sid[:8] if sid else 'unknown'}...")

    response = StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # 防止 Nginx 缓冲 SSE
        }
    )
    if sid:
        response.headers["Mcp-Session-Id"] = sid
    return response


# ============ DELETE /mcp（关闭 session）============

@router.delete("/mcp")
async def handle_mcp_delete(request: Request):
    """关闭 MCP session"""
    sid = get_session_id(request)
    if sid and sid in active_sessions:
        del active_sessions[sid]
        print(f"[MCP] Session closed: {sid[:8]}...")
    return JSONResponse(content={"status": "ok"}, status_code=200)


# ============ JSON-RPC 处理器 ============

async def handle_initialize(params: dict) -> dict:
    """处理初始化握手"""
    return {
        "protocolVersion": "2024-11-05",
        "capabilities": {
            "tools": {}
        },
        "serverInfo": {
            "name": "memory-gateway",
            "version": "2.1.0"
        }
    }


async def handle_initialized(params: dict) -> dict:
    """处理初始化完成通知"""
    return {}


async def handle_tools_list(params: dict) -> dict:
    """返回工具列表"""
    return {"tools": MCP_TOOLS}


async def handle_ping(params: dict) -> dict:
    """处理 ping 请求"""
    return {}


async def handle_tools_call(params: dict) -> dict:
    """执行工具调用"""
    tool_name = params.get("name", "")
    arguments = params.get("arguments", {})

    print(f"[MCP] Tool call: {tool_name} with {arguments}")

    if tool_name == "search_memory":
        return await execute_search_memory(arguments)
    elif tool_name == "init_context":
        return await execute_init_context(arguments)
    elif tool_name == "save_diary":
        return await execute_save_diary(arguments)
    else:
        return {
            "content": [{"type": "text", "text": f"Unknown tool: {tool_name}"}],
            "isError": True
        }


# ============ 工具执行逻辑 ============

async def execute_search_memory(args: dict) -> dict:
    """执行搜索记忆 - 优先ChromaDB语义搜索"""
    query = args.get("query", "")
    limit = args.get("limit", 5)

    if not query:
        recent = await get_recent_conversations("dream", limit)
        return format_conversations_result(recent, "最近的对话")

    # 优先使用 ChromaDB 语义搜索
    print(f"[MCP] Using ChromaDB semantic search for: {query}")
    try:
        results = await search_similar(query, "dream", limit)
        if results:
            return format_chroma_result(results, query)
    except Exception as e:
        print(f"[MCP] ChromaDB search error: {e}")

    # Fallback: MemU（超时设短一点，不要拖太久）
    try:
        if await is_available():
            print(f"[MCP] Fallback to MemU for: {query}")
            memories = await retrieve("dream", query, limit)
            if memories:
                return format_memu_result(memories, query)
    except Exception as e:
        print(f"[MCP] MemU fallback error: {e}")

    # 最终 Fallback: 关键词搜索
    print(f"[MCP] Fallback to keyword search for: {query}")
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


def format_chroma_result(results: list, query: str) -> dict:
    """格式化ChromaDB语义搜索结果"""
    if not results:
        return {
            "content": [{
                "type": "text",
                "text": f"没有找到与'{query}'相关的记忆。"
            }]
        }

    lines = [f"找到 {len(results)} 条与'{query}'相关的记忆（语义搜索）：", ""]

    for i, mem in enumerate(results, 1):
        time_str = format_time(mem.get("created_at", ""))
        distance = mem.get("distance")
        similarity = f"相似度: {1-distance:.2f}" if distance else ""

        lines.append(f"【记忆 {i}】({time_str}) {similarity}")
        lines.append(f"Dream: {mem.get('user_msg', '')[:150]}")
        lines.append(f"AI: {mem.get('assistant_msg', '')[:150]}")
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
    """格式化时间字符串 - 转换为北京时间"""
    if not time_str:
        return "未知时间"
    try:
        from datetime import timedelta
        dt = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
        beijing_time = dt + timedelta(hours=8)
        return beijing_time.strftime("%m月%d日 %H:%M")
    except Exception:
        return time_str[:16]

async def execute_save_diary(args: dict) -> dict:
    """执行写日记 - 存数据库 + 同步语雀"""
    content = args.get("content", "")
    mood = args.get("mood", "平静")

    if not content:
        return {
            "content": [{"type": "text", "text": "日记内容不能为空。"}],
            "isError": True
        }

    today = date.today()

    # 防重复：检查今天已写几篇
    try:
        from supabase import create_client
        from config import get_settings
        s = get_settings()
        supabase = create_client(s.supabase_url, s.supabase_key)

        existing = supabase.table("ai_diaries").select("id").eq(
            "diary_date", today.isoformat()
        ).execute()

        count = len(existing.data) if existing.data else 0
        if count >= 2:
            return {
                "content": [{
                    "type": "text",
                    "text": f"今天已经写了{count}篇日记了。如果Dream同意再写一篇，请再次调用此工具。"
                }]
            }
    except Exception as e:
        print(f"[MCP] 检查日记数量失败: {e}")
        count = 0

    # 1. 存入 Supabase
    saved = False
    try:
        result = supabase.table("ai_diaries").insert({
            "diary_date": today.isoformat(),
            "content": content,
            "mood": mood,
        }).execute()
        saved = bool(result.data)
    except Exception as e:
        print(f"[MCP] 日记保存失败: {e}")

    # 2. 同步到语雀
    yuque_ok = False
    try:
        yuque_result = await sync_diary_to_yuque(today, content)
        yuque_ok = yuque_result.get("success", False)
    except Exception as e:
        print(f"[MCP] 语雀同步失败: {e}")

    # 3. 返回结果
    parts = []
    if saved:
        parts.append(f"日记已保存 ✅（今日第{count+1}篇）")
    else:
        parts.append("数据库保存失败 ❌")
    if yuque_ok:
        parts.append("语雀同步成功 ✅")
    else:
        parts.append("语雀同步失败")

    return {
        "content": [{"type": "text", "text": " | ".join(parts)}]
    }

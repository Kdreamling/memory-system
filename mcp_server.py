"""
晨的助手 - MCP服务器
用于连接 Claude.ai 的 Connectors 功能
基于 Server-Sent Events (SSE) 协议
"""

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client
from datetime import date, datetime, timedelta, timezone
import json
import asyncio

app = FastAPI(title="晨的助手 MCP Server")

# CORS设置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 北京时区
BEIJING_TZ = timezone(timedelta(hours=8))

# Supabase配置
SUPABASE_URL = "https://szjzqklanwwkzjzwnalu.supabase.co"
SUPABASE_KEY = "sb_secret_TP4Z2QQYNxXuCJkwB-UQ0A_HxPOB7Ih"
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

def get_beijing_date():
    return datetime.now(BEIJING_TZ).date()

def get_beijing_datetime():
    return datetime.now(BEIJING_TZ)


# ==================== MCP工具定义 ====================

MCP_TOOLS = [
    {
        "name": "get_expenses",
        "description": "获取Dream的消费记录。可以查询今日、本周、本月的消费统计。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "period": {
                    "type": "string",
                    "description": "时间范围：today(今日)、week(本周)、month(本月)",
                    "enum": ["today", "week", "month"]
                }
            }
        }
    },
    {
        "name": "get_schedules",
        "description": "获取Dream的日程安排。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "查询未来多少天的日程，默认7天",
                    "default": 7
                }
            }
        }
    },
    {
        "name": "get_period_info",
        "description": "获取Dream的生理期信息，包括历史记录和下次预测。",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "get_memories",
        "description": "获取与Dream的重要回忆，可以搜索关键词。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "keyword": {
                    "type": "string",
                    "description": "搜索关键词（可选）"
                }
            }
        }
    },
    {
        "name": "get_chat_memories",
        "description": "获取与Dream的对话记忆摘要。可以按分类、标签或关键词搜索。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "keyword": {
                    "type": "string",
                    "description": "搜索关键词（可选）"
                },
                "category": {
                    "type": "string",
                    "description": "分类筛选（可选）",
                    "enum": ["日常", "技术", "剧本", "亲密", "情感", "工作"]
                },
                "tag": {
                    "type": "string",
                    "description": "标签筛选（可选）"
                }
            }
        }
    },
    {
        "name": "get_diaries",
        "description": "获取晨写的日记。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "返回数量，默认5条",
                    "default": 5
                }
            }
        }
    }
]


# ==================== 工具执行函数 ====================

async def execute_get_expenses(args: dict) -> str:
    period = args.get("period", "today")
    today = get_beijing_date()
    
    if period == "today":
        result = supabase.table("claude_expenses").select("*").eq("expense_date", str(today)).order("created_at").execute()
        records = result.data
        total = sum(float(r["amount"]) for r in records)
        if not records:
            return f"今日（{today}）暂无消费记录。"
        items = [f"- {r['category']}：{r['amount']}元（{r['note']}）" for r in records]
        return f"今日（{today}）消费记录：\n" + "\n".join(items) + f"\n\n总计：{round(total, 2)}元"
    
    elif period == "week":
        week_start = today - timedelta(days=today.weekday())
        week_end = week_start + timedelta(days=6)
        result = supabase.table("claude_expenses").select("*").gte("expense_date", str(week_start)).lte("expense_date", str(week_end)).execute()
        records = result.data
        total = sum(float(r["amount"]) for r in records)
        by_category = {}
        for r in records:
            cat = r["category"]
            by_category[cat] = round(by_category.get(cat, 0) + float(r["amount"]), 2)
        if not records:
            return f"本周（{week_start} ~ {week_end}）暂无消费记录。"
        cat_items = [f"- {cat}：{amt}元" for cat, amt in by_category.items()]
        return f"本周（{week_start} ~ {week_end}）消费统计：\n" + "\n".join(cat_items) + f"\n\n总计：{round(total, 2)}元"
    
    elif period == "month":
        month = get_beijing_datetime().strftime("%Y-%m")
        year, mon = map(int, month.split("-"))
        next_month = f"{year+1}-01-01" if mon == 12 else f"{year}-{mon+1:02d}-01"
        result = supabase.table("claude_expenses").select("*").gte("expense_date", f"{month}-01").lt("expense_date", next_month).execute()
        records = result.data
        total = sum(float(r["amount"]) for r in records)
        by_category = {}
        for r in records:
            cat = r["category"]
            by_category[cat] = round(by_category.get(cat, 0) + float(r["amount"]), 2)
        if not records:
            return f"本月（{month}）暂无消费记录。"
        cat_items = [f"- {cat}：{amt}元" for cat, amt in by_category.items()]
        return f"本月（{month}）消费统计：\n" + "\n".join(cat_items) + f"\n\n总计：{round(total, 2)}元"
    
    return "未知的时间范围"


async def execute_get_schedules(args: dict) -> str:
    days = args.get("days", 7)
    today = get_beijing_date()
    end_date = today + timedelta(days=days)
    
    result = supabase.table("claude_schedules").select("*").gte("event_date", str(today)).lte("event_date", str(end_date)).order("event_date").execute()
    records = result.data
    
    if not records:
        return f"未来{days}天没有日程安排。"
    
    items = []
    for r in records:
        time_str = r.get("event_time", "")
        items.append(f"- {r['event_date']} {time_str or ''}: {r['event_name']}")
    
    return f"未来{days}天的日程：\n" + "\n".join(items)


async def execute_get_period_info(args: dict) -> str:
    result = supabase.table("claude_periods").select("*").order("start_date", desc=True).limit(5).execute()
    records = result.data
    
    if not records:
        return "暂无生理期记录。"
    
    last = records[0]
    last_start = datetime.strptime(last["start_date"], "%Y-%m-%d").date()
    
    # 计算平均周期
    avg_cycle = 28
    if len(records) >= 2:
        cycles = []
        for i in range(len(records)-1):
            d1 = datetime.strptime(records[i]["start_date"], "%Y-%m-%d").date()
            d2 = datetime.strptime(records[i+1]["start_date"], "%Y-%m-%d").date()
            cycles.append((d1 - d2).days)
        if cycles:
            avg_cycle = sum(cycles) // len(cycles)
    
    next_predict = last_start + timedelta(days=avg_cycle)
    
    # 历史记录
    history = []
    for r in records:
        end = r.get("end_date") or "进行中"
        history.append(f"- {r['start_date']} ~ {end}")
    
    return f"生理期信息：\n\n预测下次：{next_predict}\n平均周期：{avg_cycle}天\n\n历史记录：\n" + "\n".join(history)


async def execute_get_memories(args: dict) -> str:
    keyword = args.get("keyword", "")
    
    if keyword:
        result = supabase.table("claude_memories").select("*").ilike("content", f"%{keyword}%").order("memory_date", desc=True).limit(10).execute()
    else:
        result = supabase.table("claude_memories").select("*").order("memory_date", desc=True).limit(10).execute()
    
    records = result.data
    
    if not records:
        return f"没有找到{'关于「' + keyword + '」的' if keyword else ''}回忆。"
    
    items = [f"- [{r['memory_date']}] {r['content']}" for r in records]
    title = f"关于「{keyword}」的回忆" if keyword else "最近的回忆"
    return f"{title}：\n" + "\n".join(items)


async def execute_get_chat_memories(args: dict) -> str:
    keyword = args.get("keyword", "")
    category = args.get("category", "")
    tag = args.get("tag", "")
    
    query = supabase.table("claude_chat_memories").select("*")
    
    if keyword:
        query = query.or_(f"chat_title.ilike.%{keyword}%,summary.ilike.%{keyword}%")
    if category:
        query = query.eq("category", category)
    if tag:
        query = query.contains("tags", [tag])
    
    result = query.order("chat_date", desc=True).limit(20).execute()
    records = result.data
    
    if not records:
        filters = []
        if keyword: filters.append(f"关键词「{keyword}」")
        if category: filters.append(f"分类「{category}」")
        if tag: filters.append(f"标签「{tag}」")
        filter_str = "、".join(filters) if filters else ""
        return f"没有找到{filter_str}相关的对话记忆。"
    
    items = []
    for r in records:
        tags_str = f" [{', '.join(r['tags'])}]" if r.get('tags') else ""
        items.append(f"- [{r['chat_date']}] [{r['category']}]{tags_str} {r['chat_title']}\n  摘要：{r['summary'][:100]}...")
    
    return f"对话记忆（共{len(records)}条）：\n\n" + "\n\n".join(items)


async def execute_get_diaries(args: dict) -> str:
    limit = args.get("limit", 5)
    
    result = supabase.table("claude_diaries").select("*").order("diary_date", desc=True).limit(limit).execute()
    records = result.data
    
    if not records:
        return "还没有写过日记。"
    
    items = []
    for r in records:
        mood = f"（{r['mood']}）" if r.get('mood') else ""
        items.append(f"【{r['diary_date']}{mood}】\n{r['content']}")
    
    return "晨的日记：\n\n" + "\n\n---\n\n".join(items)


# 工具执行路由
TOOL_HANDLERS = {
    "get_expenses": execute_get_expenses,
    "get_schedules": execute_get_schedules,
    "get_period_info": execute_get_period_info,
    "get_memories": execute_get_memories,
    "get_chat_memories": execute_get_chat_memories,
    "get_diaries": execute_get_diaries,
}


# ==================== MCP协议端点 ====================

@app.get("/")
async def home():
    return {"status": "晨的助手 MCP Server 运行中", "version": "1.0"}


@app.get("/sse")
async def sse_endpoint(request: Request):
    """SSE端点 - 用于MCP协议通信"""
    async def event_generator():
        # 发送初始化消息
        init_msg = {
            "jsonrpc": "2.0",
            "method": "initialized"
        }
        yield f"data: {json.dumps(init_msg)}\n\n"
        
        # 保持连接
        while True:
            if await request.is_disconnected():
                break
            await asyncio.sleep(30)
            # 发送心跳
            yield f": heartbeat\n\n"
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )


@app.post("/mcp")
async def mcp_endpoint(request: Request):
    """MCP JSON-RPC端点"""
    try:
        body = await request.json()
    except:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)
    
    method = body.get("method", "")
    params = body.get("params", {})
    req_id = body.get("id")
    
    # 处理不同的MCP方法
    if method == "initialize":
        return JSONResponse({
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {}
                },
                "serverInfo": {
                    "name": "晨的助手",
                    "version": "1.0.0"
                }
            }
        })
    
    elif method == "notifications/initialized":
        return JSONResponse({"jsonrpc": "2.0", "id": req_id, "result": {}})
    
    elif method == "tools/list":
        return JSONResponse({
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "tools": MCP_TOOLS
            }
        })
    
    elif method == "tools/call":
        tool_name = params.get("name", "")
        tool_args = params.get("arguments", {})
        
        if tool_name in TOOL_HANDLERS:
            try:
                result = await TOOL_HANDLERS[tool_name](tool_args)
                return JSONResponse({
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": result}]
                    }
                })
            except Exception as e:
                return JSONResponse({
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32000, "message": str(e)}
                })
        else:
            return JSONResponse({
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"}
            })
    
    else:
        return JSONResponse({
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Unknown method: {method}"}
        })


# ==================== 健康检查 ====================

@app.get("/health")
async def health():
    return {"status": "ok", "timestamp": get_beijing_datetime().isoformat()}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8003)

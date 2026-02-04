"""
晨的私人助手 API v7.0
精简版 - 3个统一工具（query/save/delete）
数据类型：expense(记账)、memory(重要回忆)、chat_memory(对话摘要)、diary(日记)
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client
from datetime import datetime, timedelta, timezone

app = FastAPI(title="晨的私人助手")

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

# 防缓存中间件
@app.middleware("http")
async def add_no_cache_headers(request: Request, call_next):
    response = await call_next(request)
    if "/mcp" in request.url.path:
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


# ==================== 健康检查 ====================

@app.get("/")
async def root():
    return {"status": "晨的私人助手运行中", "version": "7.0", "tools": 3}

@app.get("/health")
async def health():
    return {"status": "ok", "version": "7.0", "timestamp": get_beijing_datetime().isoformat()}


# ==================== MCP工具定义（3个） ====================

MCP_TOOLS = [
    {
        "name": "query",
        "description": "统一查询工具。查询Dream的数据：expense(消费记录)、memory(重要回忆)、chat_memory(对话摘要)、diary(晨的日记)。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "data_type": {
                    "type": "string",
                    "description": "数据类型",
                    "enum": ["expense", "memory", "chat_memory", "diary"]
                },
                "period": {
                    "type": "string",
                    "description": "[expense专用] 时间范围",
                    "enum": ["today", "week", "month"]
                },
                "keyword": {
                    "type": "string",
                    "description": "[memory/chat_memory专用] 搜索关键词"
                },
                "category": {
                    "type": "string",
                    "description": "[chat_memory专用] 分类筛选",
                    "enum": ["日常", "技术", "剧本", "亲密", "情感", "工作"]
                },
                "limit": {
                    "type": "integer",
                    "description": "返回数量限制，默认10"
                }
            },
            "required": ["data_type"]
        }
    },
    {
        "name": "save",
        "description": "统一保存工具。保存数据：expense(记账，需amount+category)、memory(重要回忆，需content)、chat_memory(对话摘要，需title+summary+category)、diary(日记，需content+mood)。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "data_type": {
                    "type": "string",
                    "description": "数据类型",
                    "enum": ["expense", "memory", "chat_memory", "diary"]
                },
                "amount": {
                    "type": "number",
                    "description": "[expense] 金额(元)"
                },
                "category": {
                    "type": "string",
                    "description": "[expense] 消费分类 / [chat_memory] 对话分类"
                },
                "note": {
                    "type": "string",
                    "description": "[expense] 备注"
                },
                "content": {
                    "type": "string",
                    "description": "[memory/diary] 内容"
                },
                "memory_type": {
                    "type": "string",
                    "description": "[memory] 回忆类型",
                    "enum": ["sweet", "important", "funny", "milestone"]
                },
                "keywords": {
                    "type": "string",
                    "description": "[memory] 关键词"
                },
                "title": {
                    "type": "string",
                    "description": "[chat_memory] 标题"
                },
                "summary": {
                    "type": "string",
                    "description": "[chat_memory] 摘要"
                },
                "tags": {
                    "type": "string",
                    "description": "[chat_memory] 标签，逗号分隔"
                },
                "mood": {
                    "type": "string",
                    "description": "[chat_memory/diary] 心情",
                    "enum": ["开心", "幸福", "平静", "想念", "担心", "emo", "兴奋"]
                },
                "highlights": {
                    "type": "string",
                    "description": "[diary] 今日亮点"
                }
            },
            "required": ["data_type"]
        }
    },
    {
        "name": "delete",
        "description": "统一删除工具。删除数据：expense(消费)、memory(回忆)、chat_memory(对话摘要)、diary(日记)。可按ID、关键词或删除最近一条。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "data_type": {
                    "type": "string",
                    "description": "数据类型",
                    "enum": ["expense", "memory", "chat_memory", "diary"]
                },
                "id": {
                    "type": "string",
                    "description": "记录ID（UUID）"
                },
                "keyword": {
                    "type": "string",
                    "description": "按关键词匹配删除最近一条"
                },
                "delete_latest": {
                    "type": "boolean",
                    "description": "删除最近一条记录"
                }
            },
            "required": ["data_type"]
        }
    }
]


# ==================== query 查询函数 ====================

async def mcp_query(args: dict) -> str:
    data_type = args.get("data_type")
    
    if data_type == "expense":
        return await query_expense(args)
    elif data_type == "memory":
        return await query_memory(args)
    elif data_type == "chat_memory":
        return await query_chat_memory(args)
    elif data_type == "diary":
        return await query_diary(args)
    else:
        return f"不支持的数据类型：{data_type}"

async def query_expense(args: dict) -> str:
    period = args.get("period", "today")
    today = get_beijing_date()
    
    if period == "today":
        result = supabase.table("claude_expenses").select("*").eq("expense_date", str(today)).order("created_at").execute()
        records = result.data
        total = sum(float(r["amount"]) for r in records)
        if not records:
            return f"今日（{today}）暂无消费记录。"
        items = [f"- {r['category']}：{r['amount']}元" + (f"（{r['note']}）" if r.get('note') else "") for r in records]
        return f"今日（{today}）消费：\n" + "\n".join(items) + f"\n\n总计：{round(total, 2)}元"
    
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
        return f"本周（{week_start} ~ {week_end}）消费：\n" + "\n".join(cat_items) + f"\n\n总计：{round(total, 2)}元"
    
    elif period == "month":
        now = get_beijing_datetime()
        month = now.strftime("%Y-%m")
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
        return f"本月（{month}）消费：\n" + "\n".join(cat_items) + f"\n\n总计：{round(total, 2)}元"
    
    return "未知的时间范围，请用 today/week/month"

async def query_memory(args: dict) -> str:
    keyword = args.get("keyword", "")
    limit = args.get("limit", 10)
    
    if keyword:
        result = supabase.table("claude_memories").select("*").ilike("content", f"%{keyword}%").order("memory_date", desc=True).limit(limit).execute()
    else:
        result = supabase.table("claude_memories").select("*").order("memory_date", desc=True).limit(limit).execute()
    
    records = result.data
    if not records:
        return f"没有找到{'关于「' + keyword + '」的' if keyword else ''}回忆。"
    
    items = [f"- [{r['memory_date']}] [{r.get('memory_type', '')}] {r['content']}" for r in records]
    return (f"关于「{keyword}」的回忆" if keyword else "重要回忆") + f"（{len(records)}条）：\n" + "\n".join(items)

async def query_chat_memory(args: dict) -> str:
    keyword = args.get("keyword", "")
    category = args.get("category", "")
    limit = args.get("limit", 10)
    
    query = supabase.table("claude_chat_memories").select("*")
    if keyword:
        query = query.or_(f"chat_title.ilike.%{keyword}%,summary.ilike.%{keyword}%")
    if category:
        query = query.eq("category", category)
    
    result = query.order("chat_date", desc=True).limit(limit).execute()
    records = result.data
    
    if not records:
        return "没有找到相关的对话摘要。"
    
    items = []
    for r in records:
        tags_str = f" [{', '.join(r['tags'])}]" if r.get('tags') else ""
        items.append(f"- [{r['chat_date']}] [{r['category']}]{tags_str} {r['chat_title']}\n  {r['summary'][:80]}...")
    
    return f"对话摘要（{len(records)}条）：\n\n" + "\n\n".join(items)

async def query_diary(args: dict) -> str:
    limit = args.get("limit", 5)
    result = supabase.table("claude_diaries").select("*").order("diary_date", desc=True).limit(limit).execute()
    records = result.data
    
    if not records:
        return "还没有写过日记。"
    
    items = [f"【{r['diary_date']}（{r.get('mood', '')}）】\n{r['content']}" for r in records]
    return "晨的日记：\n\n" + "\n\n---\n\n".join(items)


# ==================== save 保存函数 ====================

async def mcp_save(args: dict) -> str:
    data_type = args.get("data_type")
    
    if data_type == "expense":
        return await save_expense(args)
    elif data_type == "memory":
        return await save_memory(args)
    elif data_type == "chat_memory":
        return await save_chat_memory(args)
    elif data_type == "diary":
        return await save_diary(args)
    else:
        return f"不支持的数据类型：{data_type}"

async def save_expense(args: dict) -> str:
    amount = args.get("amount")
    category = args.get("category", "其他")
    note = args.get("note", "")
    
    if not amount:
        return "请提供金额！"
    
    # 消费分类验证
    valid_categories = ["吃饭", "购物", "交通", "娱乐", "零食", "氪金", "其他"]
    if category not in valid_categories:
        category = "其他"
    
    today = get_beijing_date()
    supabase.table("claude_expenses").insert({
        "amount": amount,
        "category": category,
        "note": note,
        "expense_date": str(today)
    }).execute()
    
    return f"记好啦！{category} {amount}元" + (f"（{note}）" if note else "") + " 💰"

async def save_memory(args: dict) -> str:
    content = args.get("content")
    memory_type = args.get("memory_type", "sweet")
    keywords = args.get("keywords", "")
    
    if not content:
        return "请提供回忆内容！"
    
    today = get_beijing_date()
    supabase.table("claude_memories").insert({
        "content": content,
        "memory_type": memory_type,
        "keywords": keywords,
        "memory_date": str(today)
    }).execute()
    
    return "这份美好的回忆已经保存啦～ 💕"

async def save_chat_memory(args: dict) -> str:
    title = args.get("title")
    summary = args.get("summary")
    category = args.get("category")
    tags = args.get("tags", "")
    mood = args.get("mood", "")
    
    if not title or not summary or not category:
        return "请提供标题、摘要和分类！"
    
    today = get_beijing_date()
    tags_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
    
    supabase.table("claude_chat_memories").insert({
        "chat_date": str(today),
        "chat_title": title,
        "summary": summary,
        "category": category,
        "tags": tags_list,
        "mood": mood if mood else None
    }).execute()
    
    return f"对话摘要已保存：{title} 🧠"

async def save_diary(args: dict) -> str:
    content = args.get("content")
    mood = args.get("mood", "平静")
    highlights = args.get("highlights", "")
    
    if not content:
        return "请提供日记内容！"
    
    today = get_beijing_date()
    supabase.table("claude_diaries").insert({
        "content": content,
        "mood": mood,
        "highlights": [highlights] if highlights else [],
        "diary_date": str(today)
    }).execute()
    
    return "日记写好啦～ 📔"


# ==================== delete 删除函数 ====================

async def mcp_delete(args: dict) -> str:
    data_type = args.get("data_type")
    record_id = args.get("id")
    keyword = args.get("keyword")
    delete_latest = args.get("delete_latest", False)
    
    # 表名映射
    table_map = {
        "expense": "claude_expenses",
        "memory": "claude_memories",
        "chat_memory": "claude_chat_memories",
        "diary": "claude_diaries"
    }
    
    # 内容字段映射
    content_field_map = {
        "expense": "note",
        "memory": "content",
        "chat_memory": "chat_title",
        "diary": "content"
    }
    
    # 类型中文名
    type_name_map = {
        "expense": "消费记录",
        "memory": "回忆",
        "chat_memory": "对话摘要",
        "diary": "日记"
    }
    
    if data_type not in table_map:
        return f"不支持的数据类型：{data_type}"
    
    table_name = table_map[data_type]
    content_field = content_field_map[data_type]
    type_name = type_name_map[data_type]
    
    if record_id:
        # 按ID删除
        found = supabase.table(table_name).select("*").eq("id", record_id).execute()
        if not found.data:
            return f"没有找到ID为 {record_id[:8]}... 的{type_name}"
        
        record = found.data[0]
        supabase.table(table_name).delete().eq("id", record_id).execute()
        preview = str(record.get(content_field, ""))[:50]
        return f"已删除{type_name}：{preview}..."
    
    elif keyword:
        # 按关键词删除
        found = supabase.table(table_name).select("*").ilike(content_field, f"%{keyword}%").order("created_at", desc=True).limit(1).execute()
        if not found.data:
            return f"没有找到包含「{keyword}」的{type_name}"
        
        record = found.data[0]
        supabase.table(table_name).delete().eq("id", record["id"]).execute()
        preview = str(record.get(content_field, ""))[:50]
        return f"已删除包含「{keyword}」的{type_name}：{preview}..."
    
    elif delete_latest:
        # 删除最近一条
        found = supabase.table(table_name).select("*").order("created_at", desc=True).limit(1).execute()
        if not found.data:
            return f"没有{type_name}可删除"
        
        record = found.data[0]
        supabase.table(table_name).delete().eq("id", record["id"]).execute()
        preview = str(record.get(content_field, ""))[:50]
        return f"已删除最近一条{type_name}：{preview}..."
    
    else:
        return "请提供 id、keyword 或设置 delete_latest=true"


# ==================== MCP Handler映射 ====================

MCP_HANDLERS = {
    "query": mcp_query,
    "save": mcp_save,
    "delete": mcp_delete,
}


# ==================== MCP端点 ====================

@app.post("/mcp")
async def mcp_endpoint(request: Request):
    try:
        body = await request.json()
    except:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)
    
    method = body.get("method", "")
    params = body.get("params", {})
    req_id = body.get("id")
    
    if method == "initialize":
        return JSONResponse({
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "晨的助手", "version": "7.0"}
            }
        })
    
    elif method == "notifications/initialized":
        return JSONResponse({"jsonrpc": "2.0", "id": req_id, "result": {}})
    
    elif method == "tools/list":
        return JSONResponse({
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"tools": MCP_TOOLS}
        })
    
    elif method == "tools/call":
        tool_name = params.get("name", "")
        tool_args = params.get("arguments", {})
        
        if tool_name in MCP_HANDLERS:
            try:
                result = await MCP_HANDLERS[tool_name](tool_args)
                return JSONResponse({
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {"content": [{"type": "text", "text": result}]}
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
    
    return JSONResponse({
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Unknown method: {method}"}
    })


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)

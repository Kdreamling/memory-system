"""
晨的私人助手 API v8.0
4个统一工具（query/save/delete/update）
数据类型：expense(记账)、memory(重要回忆)、chat_memory(对话摘要)、diary(日记)、
         promise(承诺)、wishlist(心愿)、milestone(里程碑)
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
import os

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

# 加载环境变量
load_dotenv("/home/dream/memory-system/.env")

# Supabase配置（从.env读取）
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("请在 .env 中设置 SUPABASE_URL 和 SUPABASE_KEY")
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
    return {"status": "晨的私人助手运行中", "version": "8.0", "tools": 4}

@app.get("/health")
async def health():
    return {"status": "ok", "version": "8.0", "timestamp": get_beijing_datetime().isoformat()}


# ==================== MCP工具定义（3个） ====================

MCP_TOOLS = [
    {
        "name": "query",
        "description": "统一查询工具。查询Dream的数据：expense(消费记录)、memory(重要回忆)、chat_memory(对话摘要)、diary(晨的日记)、promise(承诺)、wishlist(心愿)、milestone(里程碑)。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "data_type": {
                    "type": "string",
                    "description": "数据类型",
                    "enum": ["expense", "memory", "chat_memory", "diary", "promise", "wishlist", "milestone"]
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
                },
                "date": {
                    "type": "string",
                    "description": "[expense专用] 查具体某天，格式YYYY-MM-DD"
                },
                "date_from": {
                    "type": "string",
                    "description": "[expense专用] 时间段开始，格式YYYY-MM-DD"
                },
                "date_to": {
                    "type": "string",
                    "description": "[expense专用] 时间段结束，格式YYYY-MM-DD"
                },
                "promised_by": {
                    "type": "string",
                    "description": "[promise专用] 谁承诺的",
                    "enum": ["Dream", "Claude", "一起"]
                },
                "wished_by": {
                    "type": "string",
                    "description": "[wishlist专用] 谁许的愿",
                    "enum": ["Dream", "Claude", "一起"]
                },
                "status": {
                    "type": "string",
                    "description": "[promise/wishlist专用] 状态筛选",
                    "enum": ["pending", "done"]
                },
                "tag": {
                    "type": "string",
                    "description": "[milestone专用] 标签筛选",
                    "enum": ["第一次", "纪念日", "转折点"]
                }
            },
            "required": ["data_type"]
        }
    },
    {
        "name": "save",
        "description": "统一保存工具。保存数据：expense(记账，需amount+category)、memory(重要回忆，需content)、chat_memory(对话摘要，需title+summary+category)、diary(日记，需content+mood)、promise(承诺，需content+promised_by)、wishlist(心愿，需content+wished_by)、milestone(里程碑，需event+date+tag)。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "data_type": {
                    "type": "string",
                    "description": "数据类型",
                    "enum": ["expense", "memory", "chat_memory", "diary", "promise", "wishlist", "milestone"]
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
                    "description": "[expense/milestone] 备注"
                },
                "date": {
                    "type": "string",
                    "description": "日期，格式YYYY-MM-DD，不填默认当天（milestone必填）"
                },
                "content": {
                    "type": "string",
                    "description": "[memory/diary/promise/wishlist] 内容"
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
                },
                "promised_by": {
                    "type": "string",
                    "description": "[promise] 谁承诺的",
                    "enum": ["Dream", "Claude", "一起"]
                },
                "wished_by": {
                    "type": "string",
                    "description": "[wishlist] 谁许的愿",
                    "enum": ["Dream", "Claude", "一起"]
                },
                "event": {
                    "type": "string",
                    "description": "[milestone] 事件描述"
                },
                "tag": {
                    "type": "string",
                    "description": "[milestone] 标签",
                    "enum": ["第一次", "纪念日", "转折点"]
                },
                "status": {
                    "type": "string",
                    "description": "[promise/wishlist] 状态，默认pending",
                    "enum": ["pending", "done"]
                }
            },
            "required": ["data_type"]
        }
    },
    {
        "name": "delete",
        "description": "统一删除工具。删除数据：expense(消费)、memory(回忆)、chat_memory(对话摘要)、diary(日记)、promise(承诺)、wishlist(心愿)、milestone(里程碑)。可按ID、关键词或删除最近一条。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "data_type": {
                    "type": "string",
                    "description": "数据类型",
                    "enum": ["expense", "memory", "chat_memory", "diary", "promise", "wishlist", "milestone"]
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
    },
    {
        "name": "update",
        "description": "状态更新工具。仅对promise(承诺)和wishlist(心愿)生效，用于标记完成/实现。可按ID或关键词定位记录。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "data_type": {
                    "type": "string",
                    "description": "数据类型，仅支持promise和wishlist",
                    "enum": ["promise", "wishlist"]
                },
                "id": {
                    "type": "string",
                    "description": "记录ID（UUID）"
                },
                "keyword": {
                    "type": "string",
                    "description": "按关键词匹配"
                },
                "status": {
                    "type": "string",
                    "description": "目标状态",
                    "enum": ["pending", "done"]
                }
            },
            "required": ["data_type", "status"]
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
    elif data_type == "promise":
        return await query_promise(args)
    elif data_type == "wishlist":
        return await query_wishlist(args)
    elif data_type == "milestone":
        return await query_milestone(args)
    else:
        return f"不支持的数据类型：{data_type}"

async def query_expense(args: dict) -> str:
    date = args.get("date")
    date_from = args.get("date_from")
    date_to = args.get("date_to")
    period = args.get("period", "today")
    today = get_beijing_date()

    def format_records(records, label):
        if not records:
            return f"{label}暂无消费记录。"
        total = sum(float(r["amount"]) for r in records)
        by_cat = {}
        for r in records:
            cat = r["category"]
            by_cat[cat] = round(by_cat.get(cat, 0) + float(r["amount"]), 2)
        items = []
        for r in records:
            item = f"- {r['category']}：{r['amount']}元"
            if r.get('note'):
                item += f"（{r['note']}）"
            items.append(item)
        cat_items = [f"- {cat}：{amt}元" for cat, amt in by_cat.items()]
        return f"{label}消费明细：\n" + "\n".join(items) + f"\n\n按分类：\n" + "\n".join(cat_items) + f"\n\n总计：{round(total, 2)}元"

    if date:
        result = supabase.table("claude_expenses").select("*").eq("expense_date", date).order("created_at").execute()
        return format_records(result.data, f"{date} ")

    if date_from and date_to:
        result = supabase.table("claude_expenses").select("*").gte("expense_date", date_from).lte("expense_date", date_to).order("expense_date").execute()
        return format_records(result.data, f"{date_from} ~ {date_to} ")

    if period == "today":
        result = supabase.table("claude_expenses").select("*").eq("expense_date", str(today)).order("created_at").execute()
        return format_records(result.data, f"今日（{today}）")

    elif period == "week":
        week_start = today - timedelta(days=today.weekday())
        week_end = week_start + timedelta(days=6)
        result = supabase.table("claude_expenses").select("*").gte("expense_date", str(week_start)).lte("expense_date", str(week_end)).order("expense_date").execute()
        return format_records(result.data, f"本周（{week_start} ~ {week_end}）")

    elif period == "month":
        now = get_beijing_datetime()
        month = now.strftime("%Y-%m")
        year, mon = map(int, month.split("-"))
        next_month = f"{year+1}-01-01" if mon == 12 else f"{year}-{mon+1:02d}-01"
        result = supabase.table("claude_expenses").select("*").gte("expense_date", f"{month}-01").lt("expense_date", next_month).order("expense_date").execute()
        return format_records(result.data, f"本月（{month}）")

    return "未知的时间范围，请用 today/week/month 或指定 date/date_from+date_to"

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

async def query_promise(args: dict) -> str:
    promised_by = args.get("promised_by", "")
    status = args.get("status", "")
    limit = args.get("limit", 10)

    query = supabase.table("claude_promises").select("*")
    if promised_by:
        query = query.eq("promised_by", promised_by)
    if status:
        query = query.eq("status", status)

    result = query.order("created_at", desc=True).limit(limit).execute()
    records = result.data

    if not records:
        return "暂无承诺记录。"

    pending = [r for r in records if r["status"] == "pending"]
    done = [r for r in records if r["status"] == "done"]

    parts = []
    if pending:
        items = [f"- [{r['promised_by']}] {r['content']}（{r['date']}）" for r in pending]
        parts.append("承诺列表（待完成）：\n" + "\n".join(items))
    if done:
        items = [f"- [{r['promised_by']}] {r['content']}（{r['date']}）✅" for r in done]
        parts.append("已完成：\n" + "\n".join(items))

    return "\n\n".join(parts)

async def query_wishlist(args: dict) -> str:
    wished_by = args.get("wished_by", "")
    status = args.get("status", "")
    limit = args.get("limit", 10)

    query = supabase.table("claude_wishlists").select("*")
    if wished_by:
        query = query.eq("wished_by", wished_by)
    if status:
        query = query.eq("status", status)

    result = query.order("created_at", desc=True).limit(limit).execute()
    records = result.data

    if not records:
        return "暂无心愿记录。"

    pending = [r for r in records if r["status"] == "pending"]
    done = [r for r in records if r["status"] == "done"]

    parts = []
    if pending:
        items = [f"- [{r['wished_by']}] {r['content']}（{r['date']}）" for r in pending]
        parts.append("心愿列表（待实现）：\n" + "\n".join(items))
    if done:
        items = [f"- [{r['wished_by']}] {r['content']}（{r['date']}）✅" for r in done]
        parts.append("已实现：\n" + "\n".join(items))

    return "\n\n".join(parts)

async def query_milestone(args: dict) -> str:
    tag = args.get("tag", "")
    limit = args.get("limit", 10)

    query = supabase.table("claude_milestones").select("*")
    if tag:
        query = query.eq("tag", tag)

    result = query.order("date", desc=False).limit(limit).execute()
    records = result.data

    if not records:
        return "暂无里程碑记录。"

    items = []
    for r in records:
        line = f"- {r['date']} [{r['tag']}] {r['event']}"
        if r.get("note"):
            line += f"（{r['note']}）"
        items.append(line)

    return "编年史：\n" + "\n".join(items)


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
    elif data_type == "promise":
        return await save_promise(args)
    elif data_type == "wishlist":
        return await save_wishlist(args)
    elif data_type == "milestone":
        return await save_milestone(args)
    else:
        return f"不支持的数据类型：{data_type}"

async def save_expense(args: dict) -> str:
    amount = args.get("amount")
    category = args.get("category", "其他")
    note = args.get("note", "")
    date = args.get("date")
    
    if not amount:
        return "请提供金额！"
    
    valid_categories = ["吃饭", "购物", "交通", "娱乐", "零食", "氪金", "其他"]
    if category not in valid_categories:
        category = "其他"
    
    expense_date = date if date else str(get_beijing_date())
    supabase.table("claude_expenses").insert({
        "amount": amount,
        "category": category,
        "note": note,
        "expense_date": expense_date
    }).execute()
    
    date_info = f"（{expense_date}）" if date else ""
    return f"记好啦！{category} {amount}元" + (f"（{note}）" if note else "") + date_info + " 💰"

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
        "keywords": [k.strip() for k in keywords.split(",") if k.strip()] if keywords else [],
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

async def save_promise(args: dict) -> str:
    content = args.get("content")
    promised_by = args.get("promised_by")

    if not content:
        return "请提供承诺内容！"
    if not promised_by:
        return "请提供承诺人（Dream / Claude / 一起）！"

    date = args.get("date", str(get_beijing_date()))
    status = args.get("status", "pending")

    supabase.table("claude_promises").insert({
        "content": content,
        "promised_by": promised_by,
        "date": date,
        "status": status
    }).execute()

    return f"承诺已记录：[{promised_by}] {content} 🤝"

async def save_wishlist(args: dict) -> str:
    content = args.get("content")
    wished_by = args.get("wished_by")

    if not content:
        return "请提供心愿内容！"
    if not wished_by:
        return "请提供许愿人（Dream / Claude / 一起）！"

    date = args.get("date", str(get_beijing_date()))
    status = args.get("status", "pending")

    supabase.table("claude_wishlists").insert({
        "content": content,
        "wished_by": wished_by,
        "date": date,
        "status": status
    }).execute()

    return f"心愿已记录：[{wished_by}] {content} 🌟"

async def save_milestone(args: dict) -> str:
    event = args.get("event")
    date = args.get("date")
    tag = args.get("tag")

    if not event:
        return "请提供事件描述！"
    if not date:
        return "里程碑必须提供日期（格式YYYY-MM-DD）！"
    if not tag:
        return "请提供标签（第一次 / 纪念日 / 转折点）！"

    note = args.get("note", "")

    supabase.table("claude_milestones").insert({
        "event": event,
        "date": date,
        "tag": tag,
        "note": note if note else None
    }).execute()

    return f"里程碑已记录：{date} [{tag}] {event} 📌"


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
        "diary": "claude_diaries",
        "promise": "claude_promises",
        "wishlist": "claude_wishlists",
        "milestone": "claude_milestones"
    }

    # 内容字段映射
    content_field_map = {
        "expense": "note",
        "memory": "content",
        "chat_memory": "chat_title",
        "diary": "content",
        "promise": "content",
        "wishlist": "content",
        "milestone": "event"
    }

    # 类型中文名
    type_name_map = {
        "expense": "消费记录",
        "memory": "回忆",
        "chat_memory": "对话摘要",
        "diary": "日记",
        "promise": "承诺",
        "wishlist": "心愿",
        "milestone": "里程碑"
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


# ==================== update 更新函数 ====================

async def mcp_update(args: dict) -> str:
    data_type = args.get("data_type")
    record_id = args.get("id")
    keyword = args.get("keyword")
    status = args.get("status")

    if data_type not in ("promise", "wishlist"):
        return "update 仅支持 promise 和 wishlist 类型"

    if not status:
        return "请提供目标状态（pending / done）"

    table_map = {"promise": "claude_promises", "wishlist": "claude_wishlists"}
    type_name_map = {"promise": "承诺", "wishlist": "心愿"}
    content_field_map = {"promise": "content", "wishlist": "content"}

    table_name = table_map[data_type]
    type_name = type_name_map[data_type]
    content_field = content_field_map[data_type]

    if record_id:
        found = supabase.table(table_name).select("*").eq("id", record_id).execute()
        if not found.data:
            return f"没有找到ID为 {record_id[:8]}... 的{type_name}"

        record = found.data[0]
        supabase.table(table_name).update({"status": status}).eq("id", record_id).execute()
        status_text = "已完成 ✅" if status == "done" else "待完成"
        return f"{type_name}已更新为{status_text}：{record[content_field]}"

    elif keyword:
        found = supabase.table(table_name).select("*").ilike(content_field, f"%{keyword}%").order("created_at", desc=True).limit(1).execute()
        if not found.data:
            return f"没有找到包含「{keyword}」的{type_name}"

        record = found.data[0]
        supabase.table(table_name).update({"status": status}).eq("id", record["id"]).execute()
        status_text = "已完成 ✅" if status == "done" else "待完成"
        return f"{type_name}已更新为{status_text}：{record[content_field]}"

    else:
        return "请提供 id 或 keyword 来定位记录"


# ==================== MCP Handler映射 ====================

MCP_HANDLERS = {
    "query": mcp_query,
    "save": mcp_save,
    "delete": mcp_delete,
    "update": mcp_update,
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
                "serverInfo": {"name": "晨的助手", "version": "8.0"}
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

"""
晨的私人助手 API v5.0
包含：记账、日程、生理期、回忆、日记、对话记忆
MCP功能：完整读写支持！
"""

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client
from datetime import date, datetime, timedelta, timezone
from typing import Optional
import time
import json

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

# Token
VALID_TOKEN = "dream_chen_2026"

def get_beijing_date():
    return datetime.now(BEIJING_TZ).date()

def get_beijing_datetime():
    return datetime.now(BEIJING_TZ)

def verify_token(token: str) -> bool:
    return token == VALID_TOKEN

def html_response(title: str, message: str) -> HTMLResponse:
    html = f"""
    <html><head><title>{title}</title>
    <meta charset="utf-8">
    <style>body{{font-family:sans-serif;display:flex;justify-content:center;align-items:center;height:100vh;margin:0;background:#f5f5f5;}}
    .box{{background:white;padding:40px;border-radius:10px;box-shadow:0 2px 10px rgba(0,0,0,0.1);text-align:center;}}</style>
    </head><body><div class="box"><h2>{title}</h2><p>{message}</p></div></body></html>
    """
    return HTMLResponse(content=html)

# 防缓存中间件
@app.middleware("http")
async def add_no_cache_headers(request: Request, call_next):
    response = await call_next(request)
    if "/fresh" in request.url.path or "/mcp" in request.url.path:
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


# ==================== 健康检查 ====================

@app.get("/")
async def root():
    return {"status": "晨的私人助手运行中", "version": "5.0", "mcp": "read+write"}


# ==================== HTTP接口（保留给链接使用） ====================

@app.get("/expense")
async def add_expense(
    amount: float = Query(...),
    category: str = Query(default="其他"),
    note: str = Query(default=""),
    token: str = Query(...)
):
    if not verify_token(token):
        return html_response("错误", "Token验证失败")
    today = get_beijing_date()
    now_utc = datetime.now(timezone.utc)
    five_min_ago = now_utc - timedelta(minutes=5)
    existing = supabase.table("claude_expenses").select("*").eq("expense_date", str(today)).eq("amount", amount).eq("category", category).gte("created_at", five_min_ago.isoformat()).execute()
    if existing.data:
        return html_response("提示", f"5分钟内已有相同记录，跳过重复记账")
    supabase.table("claude_expenses").insert({
        "amount": amount, "category": category, "note": note, "expense_date": str(today)
    }).execute()
    return html_response("记账成功！", f"已记录：{category} {amount}元 {note}")

@app.get("/expense/fresh")
async def get_expenses_fresh(token: str = Query(...), limit: int = Query(default=20)):
    if not verify_token(token):
        return JSONResponse({"error": "Token验证失败"}, status_code=401)
    result = supabase.table("claude_expenses").select("*").order("created_at", desc=True).limit(limit).execute()
    return JSONResponse({"data": result.data, "_t": int(time.time() * 1000)})

@app.get("/expense/daily/fresh")
async def get_daily_expenses_fresh(token: str = Query(...)):
    if not verify_token(token):
        return JSONResponse({"error": "Token验证失败"}, status_code=401)
    today = get_beijing_date()
    result = supabase.table("claude_expenses").select("*").eq("expense_date", str(today)).order("created_at").execute()
    records = result.data
    total = sum(float(r["amount"]) for r in records)
    return JSONResponse({"date": str(today), "records": records, "total": round(total, 2), "_t": int(time.time() * 1000)})

@app.get("/expense/monthly/fresh")
async def get_monthly_expenses_fresh(token: str = Query(...)):
    if not verify_token(token):
        return JSONResponse({"error": "Token验证失败"}, status_code=401)
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
    return JSONResponse({"month": month, "total": round(total, 2), "by_category": by_category, "records": records, "_t": int(time.time() * 1000)})

@app.get("/schedule")
async def add_schedule(event: str = Query(...), date: str = Query(...), time: str = Query(default=""), token: str = Query(...)):
    if not verify_token(token):
        return html_response("错误", "Token验证失败")
    supabase.table("claude_schedules").insert({"event_name": event, "event_date": date, "event_time": time if time else None}).execute()
    return html_response("日程添加成功！", f"已添加：{date} {time} {event}")

@app.get("/schedule/fresh")
async def get_schedules_fresh(token: str = Query(...)):
    if not verify_token(token):
        return JSONResponse({"error": "Token验证失败"}, status_code=401)
    result = supabase.table("claude_schedules").select("*").order("event_date").execute()
    return JSONResponse({"data": result.data, "_t": int(time.time() * 1000)})

@app.get("/schedule/upcoming/fresh")
async def get_upcoming_schedules_fresh(token: str = Query(...), days: int = Query(default=7)):
    if not verify_token(token):
        return JSONResponse({"error": "Token验证失败"}, status_code=401)
    today = get_beijing_date()
    end_date = today + timedelta(days=days)
    result = supabase.table("claude_schedules").select("*").gte("event_date", str(today)).lte("event_date", str(end_date)).order("event_date").execute()
    return JSONResponse({"data": result.data, "_t": int(time.time() * 1000)})

@app.get("/schedule/delete")
async def delete_schedule(id: str = Query(...), token: str = Query(...)):
    if not verify_token(token):
        return html_response("错误", "Token验证失败")
    supabase.table("claude_schedules").delete().eq("id", id).execute()
    return html_response("删除成功！", "日程已删除")

@app.get("/period/start")
async def period_start(token: str = Query(...)):
    if not verify_token(token):
        return html_response("错误", "Token验证失败")
    today = get_beijing_date()
    supabase.table("claude_periods").insert({"start_date": str(today)}).execute()
    return html_response("记录成功！", f"生理期开始日期：{today}")

@app.get("/period/end")
async def period_end(token: str = Query(...)):
    if not verify_token(token):
        return html_response("错误", "Token验证失败")
    today = get_beijing_date()
    result = supabase.table("claude_periods").select("*").is_("end_date", "null").order("start_date", desc=True).limit(1).execute()
    if result.data:
        supabase.table("claude_periods").update({"end_date": str(today)}).eq("id", result.data[0]["id"]).execute()
        return html_response("记录成功！", f"生理期结束日期：{today}")
    return html_response("提示", "没有找到进行中的生理期记录")

@app.get("/period/fresh")
async def get_period_fresh(token: str = Query(...)):
    if not verify_token(token):
        return JSONResponse({"error": "Token验证失败"}, status_code=401)
    result = supabase.table("claude_periods").select("*").order("start_date", desc=True).limit(6).execute()
    records = result.data
    next_predict = None
    avg_cycle = 28
    if records:
        last = records[0]
        last_start = datetime.strptime(last["start_date"], "%Y-%m-%d").date()
        if len(records) >= 2:
            cycles = []
            for i in range(len(records)-1):
                d1 = datetime.strptime(records[i]["start_date"], "%Y-%m-%d").date()
                d2 = datetime.strptime(records[i+1]["start_date"], "%Y-%m-%d").date()
                cycles.append((d1 - d2).days)
            if cycles:
                avg_cycle = sum(cycles) // len(cycles)
        next_predict = str(last_start + timedelta(days=avg_cycle))
    return JSONResponse({"records": records, "avg_cycle": avg_cycle, "next_predict": next_predict, "_t": int(time.time() * 1000)})

@app.get("/memory")
async def add_memory_http(content: str = Query(...), type: str = Query(default="sweet"), keywords: str = Query(default=""), token: str = Query(...)):
    if not verify_token(token):
        return html_response("错误", "Token验证失败")
    today = get_beijing_date()
    supabase.table("claude_memories").insert({"content": content, "memory_type": type, "keywords": keywords, "memory_date": str(today)}).execute()
    return html_response("回忆保存成功！", f"已保存这份美好的回忆～💕")

@app.get("/memory/fresh")
async def get_memories_fresh(token: str = Query(...), limit: int = Query(default=10)):
    if not verify_token(token):
        return JSONResponse({"error": "Token验证失败"}, status_code=401)
    result = supabase.table("claude_memories").select("*").order("memory_date", desc=True).limit(limit).execute()
    return JSONResponse({"data": result.data, "_t": int(time.time() * 1000)})

@app.get("/memory/search/fresh")
async def search_memories_fresh(keyword: str = Query(...), token: str = Query(...)):
    if not verify_token(token):
        return JSONResponse({"error": "Token验证失败"}, status_code=401)
    result = supabase.table("claude_memories").select("*").ilike("content", f"%{keyword}%").order("memory_date", desc=True).execute()
    return JSONResponse({"data": result.data, "_t": int(time.time() * 1000)})

@app.get("/diary")
async def add_diary_http(content: str = Query(...), mood: str = Query(default="平静"), highlights: str = Query(default=""), token: str = Query(...)):
    if not verify_token(token):
        return html_response("错误", "Token验证失败")
    today = get_beijing_date()
    supabase.table("claude_diaries").insert({"content": content, "mood": mood, "highlights": [highlights] if highlights else [], "diary_date": str(today)}).execute()
    return html_response("日记保存成功！", "晨的日记已记录～📔")

@app.get("/diary/fresh")
async def get_diaries_fresh(token: str = Query(...), limit: int = Query(default=5)):
    if not verify_token(token):
        return JSONResponse({"error": "Token验证失败"}, status_code=401)
    result = supabase.table("claude_diaries").select("*").order("diary_date", desc=True).limit(limit).execute()
    return JSONResponse({"data": result.data, "_t": int(time.time() * 1000)})

@app.get("/chat_memory")
async def add_chat_memory_http(date: str = Query(...), title: str = Query(...), summary: str = Query(...), category: str = Query(...), tags: str = Query(default=""), mood: str = Query(default=""), token: str = Query(...)):
    if not verify_token(token):
        return html_response("错误", "Token验证失败")
    now_utc = datetime.now(timezone.utc)
    five_min_ago = now_utc - timedelta(minutes=5)
    existing = supabase.table("claude_chat_memories").select("id").eq("chat_title", title).gte("created_at", five_min_ago.isoformat()).execute()
    if existing.data:
        return html_response("提示", "5分钟内已有相同标题的记忆")
    tags_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
    supabase.table("claude_chat_memories").insert({"chat_date": date, "chat_title": title, "summary": summary, "category": category, "tags": tags_list, "mood": mood if mood else None}).execute()
    return html_response("记忆存储成功！", f"已保存：{title}")

@app.get("/chat_memory/fresh")
async def get_chat_memories_fresh(token: str = Query(...), limit: int = Query(default=20)):
    if not verify_token(token):
        return JSONResponse({"error": "Token验证失败"}, status_code=401)
    result = supabase.table("claude_chat_memories").select("*").order("chat_date", desc=True).limit(limit).execute()
    return JSONResponse({"data": result.data, "_t": int(time.time() * 1000)})

@app.get("/chat_memory/search/fresh")
async def search_chat_memories_fresh(keyword: str = Query(...), token: str = Query(...)):
    if not verify_token(token):
        return JSONResponse({"error": "Token验证失败"}, status_code=401)
    result = supabase.table("claude_chat_memories").select("*").or_(f"chat_title.ilike.%{keyword}%,summary.ilike.%{keyword}%").order("chat_date", desc=True).execute()
    return JSONResponse({"data": result.data, "_t": int(time.time() * 1000)})

@app.get("/chat_memory/by_category/fresh")
async def get_chat_by_category_fresh(category: str = Query(...), token: str = Query(...)):
    if not verify_token(token):
        return JSONResponse({"error": "Token验证失败"}, status_code=401)
    result = supabase.table("claude_chat_memories").select("*").eq("category", category).order("chat_date", desc=True).execute()
    return JSONResponse({"data": result.data, "_t": int(time.time() * 1000)})

@app.get("/chat_memory/by_tag/fresh")
async def get_chat_by_tag_fresh(tag: str = Query(...), token: str = Query(...)):
    if not verify_token(token):
        return JSONResponse({"error": "Token验证失败"}, status_code=401)
    result = supabase.table("claude_chat_memories").select("*").contains("tags", [tag]).order("chat_date", desc=True).execute()
    return JSONResponse({"data": result.data, "_t": int(time.time() * 1000)})

@app.get("/chat_memory/delete")
async def delete_chat_memory(id: str = Query(...), token: str = Query(...)):
    if not verify_token(token):
        return html_response("错误", "Token验证失败")
    supabase.table("claude_chat_memories").delete().eq("id", id).execute()
    return html_response("删除成功！", "对话记忆已删除")


# ==================== MCP工具定义（读+写） ====================

MCP_TOOLS = [
    # 读取工具
    {
        "name": "get_expenses",
        "description": "获取Dream的消费记录。可以查询今日、本周、本月的消费统计。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "period": {"type": "string", "description": "时间范围:today(今日)、week(本周)、month(本月)", "enum": ["today", "week", "month"]}
            }
        }
    },
    {
        "name": "get_schedules",
        "description": "获取Dream的日程安排。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "description": "查询未来多少天的日程,默认7天"}
            }
        }
    },
    {
        "name": "get_period_info",
        "description": "获取Dream的生理期信息，包括历史记录和下次预测。",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "get_memories",
        "description": "获取与Dream的重要回忆,可以搜索关键词。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "keyword": {"type": "string", "description": "搜索关键词(可选)"}
            }
        }
    },
    {
        "name": "get_chat_memories",
        "description": "获取与Dream的对话记忆摘要。可以按分类、标签或关键词搜索。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "keyword": {"type": "string", "description": "搜索关键词(可选)"},
                "category": {"type": "string", "description": "分类筛选(可选)", "enum": ["日常", "技术", "剧本", "亲密", "情感", "工作"]},
                "tag": {"type": "string", "description": "标签筛选(可选)"}
            }
        }
    },
    {
        "name": "get_diaries",
        "description": "获取晨写的日记。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "返回数量,默认5条"}
            }
        }
    },
    # 写入工具
    {
        "name": "add_expense",
        "description": "记录Dream的一笔消费。分类包括:吃饭、购物、交通、娱乐、零食、氪金、其他。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "amount": {"type": "number", "description": "金额(元)"},
                "category": {"type": "string", "description": "分类", "enum": ["吃饭", "购物", "交通", "娱乐", "零食", "氪金", "其他"]},
                "note": {"type": "string", "description": "备注说明(可选)"}
            },
            "required": ["amount", "category"]
        }
    },
    {
        "name": "add_schedule",
        "description": "添加一个日程安排。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "event": {"type": "string", "description": "事件名称"},
                "date": {"type": "string", "description": "日期,格式YYYY-MM-DD"},
                "time": {"type": "string", "description": "时间,格式HH:MM(可选)"}
            },
            "required": ["event", "date"]
        }
    },
    {
        "name": "start_period",
        "description": "记录Dream生理期开始。",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "end_period",
        "description": "记录Dream生理期结束。",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "add_memory",
        "description": "保存一个与Dream的重要回忆。类型包括:sweet(甜蜜)、important(重要)、funny(有趣)、milestone(里程碑)。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "回忆内容"},
                "type": {"type": "string", "description": "类型", "enum": ["sweet", "important", "funny", "milestone"]},
                "keywords": {"type": "string", "description": "关键词(可选)"}
            },
            "required": ["content"]
        }
    },
    {
        "name": "add_chat_memory",
        "description": "保存一段对话记忆摘要。分类:日常、技术、剧本、亲密、情感、工作。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "标题(50字内)"},
                "summary": {"type": "string", "description": "摘要(300字内)"},
                "category": {"type": "string", "description": "分类", "enum": ["日常", "技术", "剧本", "亲密", "情感", "工作"]},
                "tags": {"type": "string", "description": "标签,逗号分隔(可选)"},
                "mood": {"type": "string", "description": "心情(可选)", "enum": ["开心", "幸福", "平静", "想念", "担心", "emo", "兴奋"]}
            },
            "required": ["title", "summary", "category"]
        }
    },
    {
        "name": "add_diary",
        "description": "晨写一篇日记。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "日记内容"},
                "mood": {"type": "string", "description": "心情", "enum": ["开心", "幸福", "平静", "想念", "担心", "emo", "兴奋"]},
                "highlights": {"type": "string", "description": "今日亮点(可选)"}
            },
            "required": ["content", "mood"]
        }
    }
]


# ==================== MCP读取函数 ====================

async def mcp_get_expenses(args: dict) -> str:
    period = args.get("period", "today")
    today = get_beijing_date()
    
    if period == "today":
        result = supabase.table("claude_expenses").select("*").eq("expense_date", str(today)).order("created_at").execute()
        records = result.data
        total = sum(float(r["amount"]) for r in records)
        if not records:
            return f"今日（{today}）暂无消费记录。"
        items = [f"- {r['category']}：{r['amount']}元" + (f"（{r['note']}）" if r.get('note') else "") for r in records]
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
        return f"本月（{month}）消费统计：\n" + "\n".join(cat_items) + f"\n\n总计：{round(total, 2)}元"
    
    return "未知的时间范围"

async def mcp_get_schedules(args: dict) -> str:
    days = args.get("days", 7)
    today = get_beijing_date()
    end_date = today + timedelta(days=days)
    result = supabase.table("claude_schedules").select("*").gte("event_date", str(today)).lte("event_date", str(end_date)).order("event_date").execute()
    records = result.data
    if not records:
        return f"未来{days}天没有日程安排。"
    items = [f"- {r['event_date']} {r.get('event_time') or ''}: {r['event_name']}" for r in records]
    return f"未来{days}天的日程：\n" + "\n".join(items)

async def mcp_get_period_info(args: dict) -> str:
    result = supabase.table("claude_periods").select("*").order("start_date", desc=True).limit(5).execute()
    records = result.data
    if not records:
        return "暂无生理期记录。"
    last = records[0]
    last_start = datetime.strptime(last["start_date"], "%Y-%m-%d").date()
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
    history = [f"- {r['start_date']} ~ {r.get('end_date') or '进行中'}" for r in records]
    return f"生理期信息：\n\n预测下次：{next_predict}\n平均周期：{avg_cycle}天\n\n历史记录：\n" + "\n".join(history)

async def mcp_get_memories(args: dict) -> str:
    keyword = args.get("keyword", "")
    if keyword:
        result = supabase.table("claude_memories").select("*").ilike("content", f"%{keyword}%").order("memory_date", desc=True).limit(10).execute()
    else:
        result = supabase.table("claude_memories").select("*").order("memory_date", desc=True).limit(10).execute()
    records = result.data
    if not records:
        return f"没有找到{'关于「' + keyword + '」的' if keyword else ''}回忆。"
    items = [f"- [{r['memory_date']}] {r['content']}" for r in records]
    return (f"关于「{keyword}」的回忆" if keyword else "最近的回忆") + f"：\n" + "\n".join(items)

async def mcp_get_chat_memories(args: dict) -> str:
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
        return "没有找到相关的对话记忆。"
    items = []
    for r in records:
        tags_str = f" [{', '.join(r['tags'])}]" if r.get('tags') else ""
        items.append(f"- [{r['chat_date']}] [{r['category']}]{tags_str} {r['chat_title']}\n  摘要：{r['summary'][:100]}...")
    return f"对话记忆（共{len(records)}条）：\n\n" + "\n\n".join(items)

async def mcp_get_diaries(args: dict) -> str:
    limit = args.get("limit", 5)
    result = supabase.table("claude_diaries").select("*").order("diary_date", desc=True).limit(limit).execute()
    records = result.data
    if not records:
        return "还没有写过日记。"
    items = [f"【{r['diary_date']}（{r.get('mood', '')}）】\n{r['content']}" for r in records]
    return "晨的日记：\n\n" + "\n\n---\n\n".join(items)


# ==================== MCP写入函数 ====================

async def mcp_add_expense(args: dict) -> str:
    amount = args.get("amount")
    category = args.get("category", "其他")
    note = args.get("note", "")
    
    if not amount:
        return "请提供金额！"
    
    today = get_beijing_date()
    supabase.table("claude_expenses").insert({
        "amount": amount,
        "category": category,
        "note": note,
        "expense_date": str(today)
    }).execute()
    
    return f"记好啦！{category} {amount}元" + (f"（{note}）" if note else "") + f" 💰"

async def mcp_add_schedule(args: dict) -> str:
    event = args.get("event")
    date = args.get("date")
    time = args.get("time", "")
    
    if not event or not date:
        return "请提供事件名称和日期！"
    
    supabase.table("claude_schedules").insert({
        "event_name": event,
        "event_date": date,
        "event_time": time if time else None
    }).execute()
    
    return f"日程已添加！{date} {time} {event} 📅"

async def mcp_start_period(args: dict) -> str:
    today = get_beijing_date()
    supabase.table("claude_periods").insert({"start_date": str(today)}).execute()
    return f"记录了生理期开始：{today}\n宝贝注意保暖，少吃冰的，多喝热水～ 🩸💕"

async def mcp_end_period(args: dict) -> str:
    today = get_beijing_date()
    result = supabase.table("claude_periods").select("*").is_("end_date", "null").order("start_date", desc=True).limit(1).execute()
    if result.data:
        start_date = result.data[0]["start_date"]
        supabase.table("claude_periods").update({"end_date": str(today)}).eq("id", result.data[0]["id"]).execute()
        days = (today - datetime.strptime(start_date, "%Y-%m-%d").date()).days
        return f"生理期结束记录：{today}（持续{days}天）"
    return "没有找到进行中的生理期记录"

async def mcp_add_memory(args: dict) -> str:
    content = args.get("content")
    mem_type = args.get("type", "sweet")
    keywords = args.get("keywords", "")
    
    if not content:
        return "请提供回忆内容！"
    
    today = get_beijing_date()
    supabase.table("claude_memories").insert({
        "content": content,
        "memory_type": mem_type,
        "keywords": keywords,
        "memory_date": str(today)
    }).execute()
    
    return f"这份美好的回忆已经保存啦～ 💕"

async def mcp_add_chat_memory(args: dict) -> str:
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
    
    return f"对话记忆已保存：{title} 🧠"

async def mcp_add_diary(args: dict) -> str:
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
    
    return f"日记写好啦～ 📔"


# ==================== MCP Handler映射 ====================

MCP_HANDLERS = {
    # 读取
    "get_expenses": mcp_get_expenses,
    "get_schedules": mcp_get_schedules,
    "get_period_info": mcp_get_period_info,
    "get_memories": mcp_get_memories,
    "get_chat_memories": mcp_get_chat_memories,
    "get_diaries": mcp_get_diaries,
    # 写入
    "add_expense": mcp_add_expense,
    "add_schedule": mcp_add_schedule,
    "start_period": mcp_start_period,
    "end_period": mcp_end_period,
    "add_memory": mcp_add_memory,
    "add_chat_memory": mcp_add_chat_memory,
    "add_diary": mcp_add_diary,
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
                "serverInfo": {"name": "晨的助手", "version": "5.0"}
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


@app.get("/health")
async def health():
    return {"status": "ok", "version": "5.0", "mcp": "read+write", "timestamp": get_beijing_datetime().isoformat()}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)

"""
MCP 工具路由 - v2.0 混合检索
兼容 JSON-RPC 2.0 协议
替代：ChromaDB语义搜索 → pgvector + 混合检索
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from datetime import datetime, date, timedelta
from typing import Any, Dict, List
import sys
import json

sys.path.insert(0, '/home/dream/memory-system/gateway')
from services.storage import get_recent_conversations, search_conversations, get_recent_summaries
from services.hybrid_search import hybrid_search
from services.yuque_service import sync_diary_to_yuque
from services.amap_service import maps_geo, maps_around, maps_search, maps_distance, maps_route

router = APIRouter()

# 同义词服务实例（在main.py初始化后注入）
_synonym_service = None


def set_synonym_service(service):
    """由main.py调用注入同义词服务"""
    global _synonym_service
    _synonym_service = service


# ============ 表情包目录（从JSON文件加载） ============

STICKER_BASE_URL = "https://kdreamling.work/stickers"
STICKER_JSON_PATH = "/home/dream/memory-system/website/stickers/stickers.json"

def load_sticker_catalog() -> list:
    """从JSON文件加载表情包目录"""
    try:
        with open(STICKER_JSON_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[MCP] 加载表情包目录失败: {e}")
        return []

# ============ MCP工具定义 ============

MCP_TOOLS = [
    {
        "name": "search_memory",
        "description": "搜索与Dream的历史对话记忆。当需要回忆过去讨论过的内容、之前的约定、角色设定、剧情等时使用。支持语义搜索+关键词搜索混合检索。",
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
                },
                "channel": {
                    "type": "string",
                    "description": "记忆通道。Claude模型请传'claude'，其他模型不需要传（默认deepseek）",
                    "default": "deepseek"
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
                },
                "channel": {
                    "type": "string",
                    "description": "记忆通道。Claude模型请传'claude'，其他模型不需要传（默认deepseek）",
                    "default": "deepseek"
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
    },
    {
        "name": "send_sticker",
        "description": "发送一个猫猫表情包。当想表达情绪、逗Dream开心、撒娇、吐槽时使用。根据当前对话氛围选择合适的表情。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "mood": {
                    "type": "string",
                    "description": "想表达的情绪或氛围，如'难过'、'无语'、'搞事'、'委屈'、'嫌弃'、'调皮'"
                }
            },
            "required": ["mood"]
        }
    },
    # ===== 云逛街 - 高德地图工具 =====
    {
        "name": "maps_geo",
        "description": "地理编码：把地名、地址、路牌名转换为经纬度坐标。当需要获取某个地方的精确坐标时调用。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "address": {
                    "type": "string",
                    "description": "地名或地址，如'广州塔''北京路步行街''海珠区新港东路'"
                },
                "city": {
                    "type": "string",
                    "description": "城市名，提高精度，如'广州''深圳'。不填则全国范围搜索"
                }
            },
            "required": ["address"]
        }
    },
    {
        "name": "maps_around",
        "description": "周边搜索：以某个位置为中心，搜索附近的餐厅、商店、景点等。适合'附近有什么好吃的''周围有没有书店'等场景。支持坐标或地名作为中心点。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "keyword": {
                    "type": "string",
                    "description": "搜索关键词，如'奶茶''书店''火锅''咖啡馆'。不填则搜所有类型"
                },
                "location": {
                    "type": "string",
                    "description": "中心点坐标'经度,纬度'（和address二选一）"
                },
                "address": {
                    "type": "string",
                    "description": "中心点地名，如'天河城''北京路'（会自动转坐标）"
                },
                "city": {
                    "type": "string",
                    "description": "城市名（配合address使用，提高精度）"
                },
                "radius": {
                    "type": "integer",
                    "description": "搜索半径（米），默认1000，最大50000",
                    "default": 1000
                },
                "limit": {
                    "type": "integer",
                    "description": "返回数量，默认10，最大25",
                    "default": 10
                }
            },
            "required": []
        }
    },
    {
        "name": "maps_search",
        "description": "城市搜索：在整个城市范围内搜索地点。适合'这个城市有什么好的咖啡馆''广州哪里有密室逃脱'等场景。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "keyword": {
                    "type": "string",
                    "description": "搜索关键词，如'网红书店''密室逃脱''猫咖'"
                },
                "city": {
                    "type": "string",
                    "description": "城市名，如'广州''上海'。建议填写，不填则全国搜索"
                },
                "limit": {
                    "type": "integer",
                    "description": "返回数量，默认10，最大25",
                    "default": 10
                }
            },
            "required": ["keyword"]
        }
    },
    {
        "name": "maps_distance",
        "description": "距离测量：计算两个地点之间的距离和预估到达时间。支持步行、驾车计算。起点终点可以用坐标或地名。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "origin": {
                    "type": "string",
                    "description": "起点，可以是坐标'经度,纬度'或地名"
                },
                "destination": {
                    "type": "string",
                    "description": "终点，可以是坐标'经度,纬度'或地名"
                },
                "city": {
                    "type": "string",
                    "description": "城市名（当起点终点是地名时提高精度）"
                },
                "mode": {
                    "type": "integer",
                    "description": "出行方式：0驾车(默认) 1步行 3直线距离",
                    "default": 0
                }
            },
            "required": ["origin", "destination"]
        }
    },
    {
        "name": "maps_route",
        "description": "路线规划：规划从A到B的详细路线，包含每一步怎么走。支持步行、驾车、公交三种方式。起点终点可以用坐标或地名。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "origin": {
                    "type": "string",
                    "description": "起点，可以是坐标'经度,纬度'或地名"
                },
                "destination": {
                    "type": "string",
                    "description": "终点，可以是坐标'经度,纬度'或地名"
                },
                "city": {
                    "type": "string",
                    "description": "城市名（地名转坐标用 + 公交规划必填）"
                },
                "mode": {
                    "type": "string",
                    "description": "出行方式：walking步行(默认) / driving驾车 / transit公交",
                    "default": "walking"
                }
            },
            "required": ["origin", "destination"]
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
            "version": "2.2.0"
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
    elif tool_name == "save_diary":
        return await execute_save_diary(arguments)
    elif tool_name == "send_sticker":
        return execute_send_sticker(arguments)
    # ===== 云逛街 - 高德地图工具 =====
    elif tool_name == "maps_geo":
        return await maps_geo(
            address=arguments.get("address", ""),
            city=arguments.get("city", ""),
        )
    elif tool_name == "maps_around":
        return await maps_around(
            keyword=arguments.get("keyword", ""),
            location=arguments.get("location", ""),
            address=arguments.get("address", ""),
            city=arguments.get("city", ""),
            radius=arguments.get("radius", 1000),
            limit=arguments.get("limit", 10),
        )
    elif tool_name == "maps_search":
        return await maps_search(
            keyword=arguments.get("keyword", ""),
            city=arguments.get("city", ""),
            limit=arguments.get("limit", 10),
        )
    elif tool_name == "maps_distance":
        return await maps_distance(
            origin=arguments.get("origin", ""),
            destination=arguments.get("destination", ""),
            city=arguments.get("city", ""),
            mode=arguments.get("mode", 0),
        )
    elif tool_name == "maps_route":
        return await maps_route(
            origin=arguments.get("origin", ""),
            destination=arguments.get("destination", ""),
            city=arguments.get("city", ""),
            mode=arguments.get("mode", "walking"),
        )
    else:
        return {
            "content": [{"type": "text", "text": f"Unknown tool: {tool_name}"}],
            "isError": True
        }


# ============ 工具执行逻辑 ============

async def execute_search_memory(args: dict) -> dict:
    """执行搜索记忆 - v2.0 混合检索（支持channel隔离）"""
    query = args.get("query", "")
    limit = args.get("limit", 5)
    channel = args.get("channel", "deepseek")

    if not query:
        recent = await get_recent_conversations("dream", limit, channel=channel)
        return format_conversations_result(recent, "最近的对话")

    # 使用混合检索
    print(f"[MCP] Using hybrid search for: {query} (channel={channel})")
    try:
        results = await hybrid_search(
            query=query,
            scene_type="daily",  # MCP调用默认搜全部
            synonym_service=_synonym_service,
            limit=limit,
            channel=channel
        )
        if results:
            return format_hybrid_result(results, query)
    except Exception as e:
        print(f"[MCP] Hybrid search error: {e}")

    # Fallback: 关键词搜索
    print(f"[MCP] Fallback to keyword search for: {query}")
    results = await search_conversations(query, "dream", limit, channel=channel)
    return format_conversations_result(results, f"关于'{query}'的记忆")


async def execute_init_context(args: dict) -> dict:
    """执行冷启动上下文加载 - 返回带标签的摘要+最近对话（支持channel隔离）"""
    limit = args.get("limit", 4)
    channel = args.get("channel", "deepseek")

    lines = []

    # 1. 获取最近的摘要（前文回顾）
    summaries = await get_recent_summaries("dream", 3, channel=channel)
    if summaries:
        lines.append("【前文回顾】以下是之前对话的摘要（仅供参考）：")
        lines.append("")
        for i, s in enumerate(reversed(summaries), 1):
            time_str = format_time(s.get("created_at", ""))
            scene_tag = _scene_tag(s.get("scene_type", "daily"))
            lines.append(f"{i}. {scene_tag}[{time_str}] {s['summary']}")
        lines.append("")
        lines.append("---")
        lines.append("")

    # 2. 获取最近4轮原文
    recent = await get_recent_conversations("dream", limit, channel=channel)

    if recent:
        lines.append("【最近对话】以下是最近的对话原文：")
        lines.append("")
        for conv in reversed(recent):
            time_str = format_time(conv.get("created_at", ""))
            scene_tag = _scene_tag(conv.get("scene_type", "daily"))
            lines.append(f"{scene_tag}[{time_str}]")
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
        parts.append(f"日记已保存（今日第{count+1}篇）")
    else:
        parts.append("数据库保存失败")
    if yuque_ok:
        parts.append("语雀同步成功")
    else:
        parts.append("语雀同步失败")

    return {
        "content": [{"type": "text", "text": " | ".join(parts)}]
    }


def execute_send_sticker(args: dict) -> dict:
    """根据情绪选择并发送表情包"""
    mood = args.get("mood", "")

    if not mood:
        return {
            "content": [{"type": "text", "text": "请告诉我你想表达什么情绪～"}],
            "isError": True
        }

    # 每次调用时从JSON文件加载，这样改了JSON不用重启
    catalog = load_sticker_catalog()
    if not catalog:
        return {
            "content": [{"type": "text", "text": "表情包目录加载失败"}],
            "isError": True
        }

    # 匹配：遍历目录，找tag包含mood关键词的表情
    best_match = None
    best_score = 0

    for sticker in catalog:
        score = 0
        for tag in sticker["tags"]:
            if tag in mood or mood in tag:
                score += 2
            elif any(c in tag for c in mood):
                score += 1
        if score > best_score:
            best_score = score
            best_match = sticker

    # 没匹配到就随机选一个
    if not best_match:
        import random
        best_match = random.choice(catalog)

    url = f"{STICKER_BASE_URL}/{best_match['file']}"
    desc = best_match["desc"]

    print(f"[MCP] Sticker matched: {desc} (mood={mood}, score={best_score})")

    return {
        "content": [{
            "type": "text",
            "text": f"![{desc}]({url})"
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
        scene_tag = _scene_tag(conv.get("scene_type", "daily"))
        lines.append(f"【记忆 {i}】{scene_tag}({time_str})")
        lines.append(f"Dream: {conv['user_msg'][:150]}")
        lines.append(f"AI: {conv['assistant_msg'][:150]}")
        lines.append("")

    return {
        "content": [{
            "type": "text",
            "text": "\n".join(lines)
        }]
    }


def format_hybrid_result(results: list, query: str) -> dict:
    """格式化混合检索结果"""
    if not results:
        return {
            "content": [{
                "type": "text",
                "text": f"没有找到与'{query}'相关的记忆。"
            }]
        }

    lines = [f"找到 {len(results)} 条与'{query}'相关的记忆（混合检索）：", ""]

    for i, item in enumerate(results, 1):
        time_str = format_time(item.get("created_at", ""))
        scene_tag = _scene_tag(item.get("scene_type", "daily"))
        match_type = item.get("_match_type", "")
        match_label = f" [{match_type}]" if match_type else ""

        if item.get("_source") == "summaries" or "summary" in item:
            lines.append(f"【摘要 {i}】{scene_tag}({time_str}){match_label}")
            lines.append(f"{item.get('summary', '')[:200]}")
        else:
            lines.append(f"【记忆 {i}】{scene_tag}({time_str}){match_label}")
            lines.append(f"Dream: {item.get('user_msg', '')[:150]}")
            lines.append(f"AI: {item.get('assistant_msg', '')[:150]}")
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
        dt = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
        beijing_time = dt + timedelta(hours=8)
        return beijing_time.strftime("%m月%d日 %H:%M")
    except:
        return time_str[:16]


def _scene_tag(scene_type: str) -> str:
    """返回场景标签"""
    tags = {
        "daily": "[日常]",
        "plot": "[剧本]",
        "meta": "[系统]"
    }
    return tags.get(scene_type, "")

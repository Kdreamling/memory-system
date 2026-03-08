"""
会话管理 — CRUD + 场景继承
"""

import json
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional

from auth import auth_required
from config import get_settings

# ---- Supabase 客户端 ----

from supabase import create_client

_supabase = None

def get_supabase():
    global _supabase
    if _supabase is None:
        s = get_settings()
        _supabase = create_client(s.supabase_url, s.supabase_key)
    return _supabase


# ---- 请求/响应模型 ----

class CreateSessionRequest(BaseModel):
    scene_type: Optional[str] = None  # 不传则继承上一个会话的场景
    model: Optional[str] = "claude-sonnet-4-20250514"
    title: Optional[str] = None

class UpdateSessionRequest(BaseModel):
    title: Optional[str] = None
    model: Optional[str] = None
    scene_type: Optional[str] = None


# ---- 路由 ----

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


@router.post("")
async def create_session(req: CreateSessionRequest, _=Depends(auth_required)):
    """新建会话（支持场景继承）"""
    sb = get_supabase()

    # 场景继承：不传 scene_type 时，用上一个会话的场景
    scene = req.scene_type
    if scene is None:
        last = sb.table("sessions") \
            .select("scene_type") \
            .eq("user_id", "dream") \
            .order("created_at", desc=True) \
            .limit(1) \
            .execute()
        scene = last.data[0]["scene_type"] if last.data else "daily"

    now = datetime.now(timezone.utc).isoformat()
    session_id = str(uuid4())

    record = {
        "id": session_id,
        "user_id": "dream",
        "title": req.title or f"新对话",
        "model": req.model,
        "scene_type": scene,
        "message_count": 0,
        "created_at": now,
        "updated_at": now,
    }

    sb.table("sessions").insert(record).execute()
    return record


@router.get("")
async def list_sessions(
    scene: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    _=Depends(auth_required),
):
    """列出会话（支持场景筛选、分页）"""
    sb = get_supabase()
    query = sb.table("sessions") \
        .select("*") \
        .eq("user_id", "dream") \
        .order("updated_at", desc=True)

    if scene:
        query = query.eq("scene_type", scene)

    offset = (page - 1) * page_size
    query = query.range(offset, offset + page_size - 1)

    result = query.execute()
    return {"sessions": result.data, "page": page, "page_size": page_size}


@router.get("/{session_id}")
async def get_session(session_id: str, _=Depends(auth_required)):
    """获取会话详情"""
    sb = get_supabase()
    result = sb.table("sessions").select("*").eq("id", session_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="会话不存在")
    return result.data[0]


@router.patch("/{session_id}")
async def update_session(
    session_id: str,
    req: UpdateSessionRequest,
    _=Depends(auth_required),
):
    """修改会话标题/模型/场景"""
    sb = get_supabase()
    updates = {"updated_at": datetime.now(timezone.utc).isoformat()}

    if req.title is not None:
        updates["title"] = req.title
    if req.model is not None:
        updates["model"] = req.model
    if req.scene_type is not None:
        updates["scene_type"] = req.scene_type

    result = sb.table("sessions").update(updates).eq("id", session_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="会话不存在")
    return result.data[0]


@router.delete("/{session_id}")
async def delete_session(session_id: str, _=Depends(auth_required)):
    """删除会话及其所有消息"""
    sb = get_supabase()

    # 先删关联的 conversations
    sb.table("conversations").delete().eq("session_id", session_id).execute()

    # 再删 session
    result = sb.table("sessions").delete().eq("id", session_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"ok": True}


@router.get("/{session_id}/messages")
async def get_messages(
    session_id: str,
    page: int = 1,
    page_size: int = 50,
    _=Depends(auth_required),
):
    """拉取会话的历史消息（分页，最新的在前）"""
    sb = get_supabase()
    offset = (page - 1) * page_size

    result = sb.table("conversations") \
        .select("id, user_msg, assistant_msg, thinking_summary, model, token_count, scene_type, created_at") \
        .eq("session_id", session_id) \
        .order("created_at", desc=True) \
        .range(offset, offset + page_size - 1) \
        .execute()

    return {"messages": result.data, "page": page, "page_size": page_size}


@router.post("/{session_id}/export")
async def export_session(session_id: str, _=Depends(auth_required)):
    """导出单个会话为 JSON"""
    sb = get_supabase()

    session = sb.table("sessions").select("*").eq("id", session_id).execute()
    if not session.data:
        raise HTTPException(status_code=404, detail="会话不存在")

    messages = sb.table("conversations") \
        .select("*") \
        .eq("session_id", session_id) \
        .order("created_at", desc=False) \
        .execute()

    return {
        "session": session.data[0],
        "messages": messages.data,
        "exported_at": datetime.now(timezone.utc).isoformat(),
    }


# ---- 辅助函数（供其他模块调用）----

async def update_session_stats(session_id: str):
    """更新会话的消息计数和时间戳（在存消息后异步调用）"""
    if not session_id:
        return
    sb = get_supabase()
    try:
        count_result = sb.table("conversations") \
            .select("id", count="exact") \
            .eq("session_id", session_id) \
            .execute()
        msg_count = count_result.count or 0

        sb.table("sessions").update({
            "message_count": msg_count,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", session_id).execute()
    except Exception as e:
        print(f"[sessions] update_session_stats error: {e}")
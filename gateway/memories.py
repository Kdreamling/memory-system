"""
记忆管理 — CRUD
"""

from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional

from auth import auth_required
from config import get_supabase


# ---- 请求模型 ----

class CreateMemoryRequest(BaseModel):
    content: str
    layer: str = "core_living"
    scene_type: Optional[str] = None
    source: str = "manual"

class UpdateMemoryRequest(BaseModel):
    content: Optional[str] = None
    layer: Optional[str] = None
    scene_type: Optional[str] = None


# ---- 路由 ----

router = APIRouter(prefix="/api/memories", tags=["memories"])


@router.get("")
async def list_memories(
    layer: Optional[str] = Query(None),
    scene_type: Optional[str] = Query(None),
    _=Depends(auth_required),
):
    """查看记忆（支持 layer/scene 筛选）"""
    sb = get_supabase()
    query = sb.table("memories").select("*").order("updated_at", desc=True)

    if layer:
        query = query.eq("layer", layer)
    if scene_type:
        query = query.eq("scene_type", scene_type)

    result = query.execute()
    return {"memories": result.data}


@router.post("")
async def create_memory(req: CreateMemoryRequest, _=Depends(auth_required)):
    """新增记忆"""
    sb = get_supabase()
    now = datetime.now(timezone.utc).isoformat()

    record = {
        "id": str(uuid4()),
        "content": req.content,
        "layer": req.layer,
        "scene_type": req.scene_type,
        "source": req.source,
        "created_at": now,
        "updated_at": now,
    }

    sb.table("memories").insert(record).execute()
    return record


@router.patch("/{memory_id}")
async def update_memory(
    memory_id: str,
    req: UpdateMemoryRequest,
    _=Depends(auth_required),
):
    """编辑记忆"""
    sb = get_supabase()
    updates = {"updated_at": datetime.now(timezone.utc).isoformat()}

    if req.content is not None:
        updates["content"] = req.content
    if req.layer is not None:
        updates["layer"] = req.layer
    if req.scene_type is not None:
        updates["scene_type"] = req.scene_type

    result = sb.table("memories").update(updates).eq("id", memory_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="记忆不存在")
    return result.data[0]


@router.delete("/{memory_id}")
async def delete_memory(memory_id: str, _=Depends(auth_required)):
    """删除记忆"""
    sb = get_supabase()
    result = sb.table("memories").delete().eq("id", memory_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="记忆不存在")
    return {"ok": True}

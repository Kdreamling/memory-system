#!/usr/bin/env python3
"""
日记只读 API
端口: 8003
提供 ai_diaries 和 claude_diaries 表的只读访问
"""

import os
from datetime import datetime
from typing import Optional
from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from supabase import create_client, Client
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("请设置 SUPABASE_URL 和 SUPABASE_KEY 环境变量")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

app = FastAPI(
    title="Dream's Diary API",
    description="只读日记 API",
    version="1.0.0"
)

# CORS 配置 - 允许前端访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境建议改为具体域名
    allow_credentials=True,
    allow_methods=["GET"],  # 只允许 GET 请求
    allow_headers=["*"],
)


class DiaryEntry(BaseModel):
    """日记条目"""
    id: Optional[int] = None
    content: str
    diary_date: str
    source: str  # "kelivo" 或 "chen"
    mood: Optional[str] = None
    highlights: Optional[str] = None


@app.get("/")
async def root():
    """API 根路径"""
    return {"message": "Dream's Diary API", "version": "1.0.0"}


@app.get("/api/diaries")
async def get_diaries(
    limit: int = Query(default=20, ge=1, le=100, description="返回条数"),
    offset: int = Query(default=0, ge=0, description="偏移量"),
    source: Optional[str] = Query(default=None, description="来源筛选: kelivo 或 chen")
):
    """
    获取日记列表，按时间倒序排列
    """
    diaries = []

    try:
        # 获取 Kelivo 日记 (ai_diaries)
        if source is None or source == "kelivo":
            kelivo_response = supabase.table("ai_diaries")\
                .select("id, content, diary_date")\
                .order("diary_date", desc=True)\
                .limit(limit if source == "kelivo" else limit * 2)\
                .execute()

            for entry in kelivo_response.data:
                diaries.append({
                    "id": entry.get("id"),
                    "content": entry.get("content", ""),
                    "diary_date": entry.get("diary_date", ""),
                    "source": "kelivo",
                    "source_name": "Kelivo · Krueger",
                    "mood": None,
                    "highlights": None
                })

        # 获取晨的日记 (claude_diaries)
        if source is None or source == "chen":
            chen_response = supabase.table("claude_diaries")\
                .select("id, content, mood, highlights, diary_date")\
                .order("diary_date", desc=True)\
                .limit(limit if source == "chen" else limit * 2)\
                .execute()

            for entry in chen_response.data:
                diaries.append({
                    "id": entry.get("id"),
                    "content": entry.get("content", ""),
                    "diary_date": entry.get("diary_date", ""),
                    "source": "chen",
                    "source_name": "晨",
                    "mood": entry.get("mood"),
                    "highlights": entry.get("highlights")
                })

        # 按日期倒序排序
        diaries.sort(key=lambda x: x["diary_date"], reverse=True)

        # 应用分页
        diaries = diaries[offset:offset + limit]

        return {
            "success": True,
            "data": diaries,
            "count": len(diaries)
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取日记失败: {str(e)}")


@app.get("/api/diaries/{diary_id}")
async def get_diary(diary_id: int, source: str = Query(..., description="来源: kelivo 或 chen")):
    """
    获取单篇日记详情
    """
    try:
        table_name = "ai_diaries" if source == "kelivo" else "claude_diaries"

        response = supabase.table(table_name)\
            .select("*")\
            .eq("id", diary_id)\
            .single()\
            .execute()

        if not response.data:
            raise HTTPException(status_code=404, detail="日记不存在")

        entry = response.data
        return {
            "success": True,
            "data": {
                "id": entry.get("id"),
                "content": entry.get("content", ""),
                "diary_date": entry.get("diary_date", ""),
                "source": source,
                "source_name": "Kelivo · Krueger" if source == "kelivo" else "晨",
                "mood": entry.get("mood") if source == "chen" else None,
                "highlights": entry.get("highlights") if source == "chen" else None
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取日记失败: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8003)

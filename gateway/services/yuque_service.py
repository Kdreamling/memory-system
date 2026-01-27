"""语雀同步服务 - 将AI日记同步到语雀"""
import httpx
from datetime import date
import sys
sys.path.insert(0, '/home/dream/memory-system/gateway')
from config import get_settings

settings = get_settings()

YUQUE_API = "https://www.yuque.com/api/v2"
REPO_ID = "74614901"  # 你的知识库ID


async def create_diary_doc(diary_date: date, content: str) -> dict:
    """在语雀创建日记文档"""
    
    title = f"📔 {diary_date.strftime('%Y年%m月%d日')} 的日记"
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{YUQUE_API}/repos/{REPO_ID}/docs",
            headers={
                "X-Auth-Token": settings.yuque_token,
                "Content-Type": "application/json"
            },
            json={
                "title": title,
                "slug": f"diary-{diary_date.isoformat()}",
                "body": content,
                "format": "markdown"
            }
        )
        
        data = response.json()
        
        if "data" in data:
            doc_id = data["data"]["id"]
            doc_url = f"https://www.yuque.com/kdreamling/itmns3/diary-{diary_date.isoformat()}"
            return {"success": True, "doc_id": doc_id, "url": doc_url}
        else:
            return {"success": False, "error": data}


async def sync_diary_to_yuque(diary_date: date, content: str) -> dict:
    """同步日记到语雀（主函数）"""
    print(f"同步日记到语雀: {diary_date}")
    result = await create_diary_doc(diary_date, content)
    if result["success"]:
        print(f"同步成功: {result['url']}")
    else:
        print(f"同步失败: {result['error']}")
    return result

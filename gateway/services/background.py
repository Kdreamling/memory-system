"""
后台同步服务 - 将对话异步同步到MemU
"""

import asyncio
from typing import Optional
from datetime import datetime

import sys
sys.path.insert(0, '/home/dream/memory-system/gateway')

from services.storage import get_unsynced_conversations, mark_synced
from services.memu_client import memorize, is_available


class BackgroundSyncService:
    """
    后台同步服务
    定期将Supabase中未同步的对话同步到MemU
    """
    
    def __init__(self, interval: int = 30):
        """
        Args:
            interval: 同步间隔（秒）
        """
        self.interval = interval
        self.running = False
        self._task: Optional[asyncio.Task] = None
        self._synced_count = 0
        self._error_count = 0
    
    async def start(self):
        """启动后台同步"""
        if self.running:
            print("[BackgroundSync] Already running")
            return
        
        self.running = True
        self._task = asyncio.create_task(self._sync_loop())
        print(f"[BackgroundSync] Started (interval: {self.interval}s)")
    
    async def stop(self):
        """停止后台同步"""
        self.running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        print(f"[BackgroundSync] Stopped (synced: {self._synced_count}, errors: {self._error_count})")
    
    async def _sync_loop(self):
        """主同步循环"""
        # 启动后等待一会儿，让MemU有时间启动
        await asyncio.sleep(10)
        
        while self.running:
            try:
                # 检查MemU是否可用
                if not await is_available():
                    print("[BackgroundSync] MemU not available, skipping...")
                    await asyncio.sleep(self.interval * 2)
                    continue
                
                # 获取未同步的对话
                unsynced = await get_unsynced_conversations(limit=10)
                
                if unsynced:
                    print(f"[BackgroundSync] Found {len(unsynced)} unsynced conversations")
                
                for conv in unsynced:
                    try:
                        # 格式化对话
                        conversation = f"User: {conv['user_msg']}\nAssistant: {conv['assistant_msg']}"
                        
                        # 同步到MemU
                        success = await memorize(
                            user_id=conv.get('user_id', 'dream'),
                            conversation=conversation
                        )
                        
                        if success:
                            await mark_synced(conv['id'])
                            self._synced_count += 1
                            print(f"[BackgroundSync] Synced {conv['id'][:8]}...")
                        else:
                            self._error_count += 1
                        
                        # 避免请求过快
                        await asyncio.sleep(1)
                        
                    except Exception as e:
                        print(f"[BackgroundSync] Error syncing {conv['id'][:8]}: {e}")
                        self._error_count += 1
                
                # 等待下一次同步
                await asyncio.sleep(self.interval)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[BackgroundSync] Loop error: {e}")
                self._error_count += 1
                await asyncio.sleep(self.interval * 2)
    
    def get_stats(self) -> dict:
        """获取同步统计"""
        return {
            "running": self.running,
            "synced_count": self._synced_count,
            "error_count": self._error_count
        }


# 全局实例
sync_service = BackgroundSyncService(interval=30)

#!/usr/bin/env python3
"""每日清理过期向量的定时任务脚本"""

import sys
sys.path.insert(0, '/home/dream/memory-system/gateway')

import asyncio
from services.embedding_service import cleanup_old_embeddings_real

async def main():
    print("=== Starting daily cleanup ===")
    deleted = await cleanup_old_embeddings_real(days=7)
    print(f"=== Cleanup complete: {deleted} records deleted ===")

if __name__ == "__main__":
    asyncio.run(main())

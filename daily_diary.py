#!/usr/bin/env python3
"""每日日记执行脚本 - 由cron调用"""
import asyncio
import sys
from datetime import date

sys.path.insert(0, '/home/dream/memory-system/gateway')
from services.diary_service import write_daily_diary
from services.yuque_service import sync_diary_to_yuque


async def main():
    # 可以通过命令行参数指定模型，默认deepseek-chat
    model = sys.argv[1] if len(sys.argv) > 1 else "deepseek-chat"
    
    result = await write_daily_diary(model=model)
    
    print("="*50)
    print(f"日期: {result['date']}")
    print(f"字数: {result['diary_length']}")
    print(f"保存: {'成功' if result['saved'] else '失败'}")
    print("="*50)
    print(result['content'])
    
    # 同步到语雀
    if result['saved'] and result['content']:
        print("\n" + "="*50)
        print("正在同步到语雀...")
        yuque_result = await sync_diary_to_yuque(
            date.fromisoformat(result['date']),
            result['content']
        )
        if yuque_result['success']:
            print(f"语雀链接: {yuque_result['url']}")
        print("="*50)


if __name__ == "__main__":
    asyncio.run(main())

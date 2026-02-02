#!/usr/bin/env python3
"""每日日记执行脚本 - 由cron调用"""
import asyncio
import sys
import httpx
import os
from datetime import date

sys.path.insert(0, '/home/dream/memory-system/gateway')
from services.diary_service import write_daily_diary
from services.yuque_service import sync_diary_to_yuque

# 加载环境变量
from dotenv import load_dotenv
load_dotenv('/home/dream/memory-system/.env')


async def send_wechat(title: str, content: str):
    """通过Server酱推送到微信"""
    key = os.getenv('SERVERCHAN_KEY')
    if not key:
        print("未配置SERVERCHAN_KEY，跳过微信推送")
        return False
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"https://sctapi.ftqq.com/{key}.send",
                data={"title": title, "desp": content}
            )
            data = response.json()
            if data.get("code") == 0:
                print("微信推送成功！")
                return True
            else:
                print(f"微信推送失败: {data}")
                return False
    except Exception as e:
        print(f"微信推送错误: {e}")
        return False


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
    yuque_url = ""
    if result['saved'] and result['content']:
        print("\n" + "="*50)
        print("正在同步到语雀...")
        yuque_result = await sync_diary_to_yuque(
            date.fromisoformat(result['date']),
            result['content']
        )
        if yuque_result['success']:
            yuque_url = yuque_result['url']
            print(f"语雀链接: {yuque_url}")
        print("="*50)
    
    # 推送到微信
    if result['saved'] and result['content']:
        print("\n正在推送到微信...")
        title = f"📔 {result['date']} 的日记"
        # 内容加上语雀链接
        content = result['content']
        if yuque_url:
            content += f"\n\n---\n[在语雀查看]({yuque_url})"
        #         await send_wechat(title, content)


if __name__ == "__main__":
    asyncio.run(main())

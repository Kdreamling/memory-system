"""
同义词映射服务
启动时从 synonym_map 表加载映射，对搜索关键词进行同义词扩展
"""

import re
import asyncio
from typing import List, Dict
import sys

sys.path.insert(0, '/home/dream/memory-system/gateway')
from config import get_settings

settings = get_settings()


class SynonymService:
    """同义词映射与查询扩展"""

    def __init__(self):
        # term -> [synonyms] 映射
        self._mapping: Dict[str, List[str]] = {}
        # 反向映射：任意同义词 -> 主词的同义词列表
        self._reverse: Dict[str, List[str]] = {}
        self._loaded = False

    async def load(self):
        """从数据库加载映射表"""
        try:
            from supabase import create_client
            supabase = create_client(settings.supabase_url, settings.supabase_key)

            def _fetch():
                result = supabase.table("synonym_map").select("term, synonyms").execute()
                return result.data if result.data else []

            rows = await asyncio.to_thread(_fetch)

            self._mapping.clear()
            self._reverse.clear()

            for row in rows:
                term = row["term"]
                synonyms = row["synonyms"]
                self._mapping[term] = synonyms
                # 建立反向索引
                for syn in synonyms:
                    self._reverse[syn.lower()] = synonyms

            self._loaded = True
            print(f"[Synonym] Loaded {len(self._mapping)} synonym groups")
        except Exception as e:
            print(f"[Synonym] Load error: {e}")
            # 加载失败不影响系统运行，用空映射
            self._loaded = True

    def expand(self, query: str) -> List[str]:
        """
        对查询进行同义词扩展
        返回扩展后的关键词列表（包含原始词）
        """
        if not query:
            return []

        # 简单分词：按空格、标点、中英文边界分割
        tokens = self._tokenize(query)
        expanded = set(tokens)

        for token in tokens:
            token_lower = token.lower()
            # 在反向索引中查找
            if token_lower in self._reverse:
                expanded.update(self._reverse[token_lower])
            # 也检查原始大小写
            if token in self._reverse:
                expanded.update(self._reverse[token])

        return list(expanded)

    async def refresh(self):
        """重新加载映射表"""
        await self.load()

    def _tokenize(self, text: str) -> List[str]:
        """
        简单分词：按空格和标点分割，保留有意义的token
        不依赖jieba等重量级依赖
        """
        # 按空格、标点、特殊符号分割
        # 保留中文连续字符、英文单词、数字
        tokens = re.findall(r'[\u4e00-\u9fff]+|[a-zA-Z]+|[0-9]+', text)
        # 对中文进行更细粒度的切分：2-4字的ngram
        result = []
        for token in tokens:
            result.append(token)
            # 如果是纯中文且长度>2，生成2字和3字的ngram
            if re.match(r'^[\u4e00-\u9fff]+$', token) and len(token) > 2:
                for n in range(2, min(len(token) + 1, 5)):
                    for i in range(len(token) - n + 1):
                        ngram = token[i:i + n]
                        result.append(ngram)
        return list(set(result))

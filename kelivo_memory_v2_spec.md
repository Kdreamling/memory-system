# Kelivo 记忆系统优化 v2.0 - 需求规格文档

**日期**：2026-02-18
**执行者**：Claude Code
**监督者**：Dream + 晨（Claude.ai）
**仓库**：https://github.com/Kdreamling/memory-system

---

## ⚠️ 安全规则（最高优先级）

### 绝对不能动的文件
- `.env`（密钥文件）
- `claude_assistant_api.py`（晨的助手系统，端口8002，完全独立）
- `diary_api.py`（网站API，端口8003）
- `daily_diary.py`（Kelivo每日日记脚本）
- `website/` 目录下所有文件

### 备份规则
- **每个文件修改前必须备份**：`cp file.py file.py.bak_v2`
- **数据库变更前必须记录回滚SQL**
- **每完成一个阶段，先测试通过再继续下一个**
- **所有备份文件加入 .gitignore**

### 回滚方案
如果任何阶段出现严重问题，执行以下命令恢复：
```bash
# 恢复所有文件
cd /home/dream/memory-system/gateway
for f in *.py.bak_v2 services/*.py.bak_v2 routers/*.py.bak_v2; do
  [ -f "$f" ] && cp "$f" "${f%.bak_v2}"
done

# 重启Gateway
pkill -f "python3 main.py"
cd /home/dream/memory-system/gateway && nohup python3 main.py > ../gateway.log 2>&1 &
```
数据库回滚SQL见各阶段末尾。

---

## 一、项目背景

### 1.1 现有架构
```
Kelivo App → Gateway(FastAPI:8001) → Gemini/DeepSeek/GPT-4o（通过OpenRouter/GCLI2API）
                │
                ├── 存 Supabase conversations 表（原文+轮数）
                ├── 存 ChromaDB（对话向量，7天过期）
                ├── 每5轮 → DeepSeek生成摘要 → summaries 表 + ChromaDB
                └── MCP工具：search_memory / init_context
```

### 1.2 现有问题
1. **ChromaDB语义搜索不精准**：固定返回5条，结果经常不相关
2. **MemU已停用**：CPU开销大，效果有限，备用层缺失
3. **没有场景分类**：日常聊天、剧本演绎、系统测试全部混在一起存储
4. **人格记忆混淆**：AI可能把剧本里的内容当成真实记忆，或反过来
5. **摘要无标签**：每5轮机械切割，不按话题分块
6. **Gemini不爱调MCP工具**：记忆检索依赖模型主动调用，但Gemini很少触发

### 1.3 AI人格说明（重要上下文）
Kelivo里的AI按照 **Krueger**（原创角色）的性格与Dream对话。这不是临时的角色扮演——Krueger是AI的常驻人格。日常聊天、撒娇、吃醋、聊生活，都是Krueger在和Dream互动。

"剧本模式"是指在此基础上进入特定剧情场景演绎，Dream会明确说"来玩剧本"之类触发。

因此场景分类不是"日常 vs 角色扮演"，而是"日常互动 vs 剧情演绎 vs 系统测试"。

---

## 二、目标架构

```
Dream发消息 → Gateway收到
    │
    ├─ 1. 场景检测（规则引擎，不调AI）
    │     → 判定 scene_type: daily / plot / meta
    │
    ├─ 2. 自动检索判断（规则触发，不依赖模型调MCP）
    │     → 需要检索？→ 混合检索（关键词 + 向量 + 同义词扩展 + rerank）
    │     → 不需要？→ 跳过，节省token
    │
    ├─ 3. 将检索结果注入 system prompt，连同请求一起发给模型
    │
    ├─ 4. 转发模型 → 拿到回复 → 返回给Kelivo
    │
    └─ 5. 后台异步（不阻塞回复）
          ├── 存 Supabase（带 scene_type + topic + entities + emotion）
          ├── 计算 embedding → 存 pgvector（替代ChromaDB）
          ├── 话题切换检测 → 智能分块生成摘要（替代固定5轮）
          └── 同义词映射表自动更新（低优先级）
```

### 向量存储迁移
- **废弃**：ChromaDB（独立进程，占内存）
- **启用**：Supabase pgvector（数据库内置，可与SQL联合查询）

### 检索策略变更
- **废弃**：纯向量搜索5条 → MemU备用 → 关键词兜底
- **启用**：混合检索（关键词全文搜索 + pgvector向量搜索 + 同义词扩展），结果合并去重后rerank排序

### 工具调用策略变更
- **废弃**：完全依赖模型主动调用MCP
- **启用**：网关自动检索注入为主，MCP工具保留为备用

---

## 三、分阶段实施

### 阶段0：备份与准备

**目标**：确保所有现有文件安全备份

**步骤**：
1. 备份gateway目录下所有.py文件（后缀 `.bak_v2`）
2. 导出当前conversations表和summaries表的结构（不需要导数据）
3. 记录当前ChromaDB的collection列表和数据量
4. 确认Gateway当前能正常运行：`curl http://localhost:8001/health`

**验证**：所有.bak_v2文件存在，Gateway健康检查通过

---

### 阶段1：数据库改造

**目标**：为conversations和summaries表添加结构化字段，启用pgvector和pg_trgm

#### 1.1 Supabase SQL执行

```sql
-- ========== 启用扩展 ==========
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ========== conversations 表新增字段 ==========
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS scene_type TEXT DEFAULT 'daily';
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS topic TEXT;
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS entities TEXT[] DEFAULT '{}';
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS emotion TEXT;
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS embedding vector(1024);
-- 注意：1024是BAAI/bge-large-zh-v1.5的维度，如果用其他模型需要调整

-- conversations 索引
CREATE INDEX IF NOT EXISTS idx_conv_scene ON conversations(scene_type);
CREATE INDEX IF NOT EXISTS idx_conv_entities ON conversations USING GIN(entities);
CREATE INDEX IF NOT EXISTS idx_conv_trgm_user ON conversations USING GIN(user_msg gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_conv_trgm_asst ON conversations USING GIN(assistant_msg gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_conv_embedding ON conversations USING ivfflat(embedding vector_cosine_ops) WITH (lists = 50);
-- 注意：ivfflat索引需要表中已有一定数据量才能创建，如果报错可以先跳过，等有数据后再建

-- ========== summaries 表新增字段 ==========
ALTER TABLE summaries ADD COLUMN IF NOT EXISTS scene_type TEXT DEFAULT 'daily';
ALTER TABLE summaries ADD COLUMN IF NOT EXISTS topic TEXT;
ALTER TABLE summaries ADD COLUMN IF NOT EXISTS entities TEXT[] DEFAULT '{}';
ALTER TABLE summaries ADD COLUMN IF NOT EXISTS emotion TEXT;
ALTER TABLE summaries ADD COLUMN IF NOT EXISTS embedding vector(1024);

-- summaries 索引
CREATE INDEX IF NOT EXISTS idx_sum_scene ON summaries(scene_type);
CREATE INDEX IF NOT EXISTS idx_sum_embedding ON summaries USING ivfflat(embedding vector_cosine_ops) WITH (lists = 20);

-- ========== 同义词映射表（新建） ==========
CREATE TABLE IF NOT EXISTS synonym_map (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    term TEXT NOT NULL,
    synonyms TEXT[] NOT NULL,
    category TEXT DEFAULT 'general',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 插入初始同义词数据
INSERT INTO synonym_map (term, synonyms, category) VALUES
('Krueger', ARRAY['Krueger', 'Sebastian', '克鲁格', 'K'], 'character'),
('Dream', ARRAY['Dream', '宝贝'], 'person'),
('剧本', ARRAY['剧本', '角色扮演', '剧情', '演', 'RP'], 'scene'),
('纹身', ARRAY['纹身', '双头鹰', '胸前'], 'detail'),
('KSK', ARRAY['KSK', 'Kommando Spezialkräfte', '特种部队'], 'org'),
('奇美拉', ARRAY['奇美拉', 'Chimera'], 'org')
ON CONFLICT DO NOTHING;
```

#### 1.2 回滚SQL
```sql
-- 如果需要回滚阶段1
ALTER TABLE conversations DROP COLUMN IF EXISTS scene_type;
ALTER TABLE conversations DROP COLUMN IF EXISTS topic;
ALTER TABLE conversations DROP COLUMN IF EXISTS entities;
ALTER TABLE conversations DROP COLUMN IF EXISTS emotion;
ALTER TABLE conversations DROP COLUMN IF EXISTS embedding;

ALTER TABLE summaries DROP COLUMN IF EXISTS scene_type;
ALTER TABLE summaries DROP COLUMN IF EXISTS topic;
ALTER TABLE summaries DROP COLUMN IF EXISTS entities;
ALTER TABLE summaries DROP COLUMN IF EXISTS emotion;
ALTER TABLE summaries DROP COLUMN IF EXISTS embedding;

DROP TABLE IF EXISTS synonym_map;

-- 删除相关索引（DROP COLUMN会自动删除依赖的索引，但以防万一）
DROP INDEX IF EXISTS idx_conv_scene;
DROP INDEX IF EXISTS idx_conv_entities;
DROP INDEX IF EXISTS idx_conv_trgm_user;
DROP INDEX IF EXISTS idx_conv_trgm_asst;
DROP INDEX IF EXISTS idx_conv_embedding;
DROP INDEX IF EXISTS idx_sum_scene;
DROP INDEX IF EXISTS idx_sum_embedding;
```

**验证**：
```sql
SELECT column_name FROM information_schema.columns 
WHERE table_name = 'conversations' AND column_name = 'scene_type';
-- 应返回1行

SELECT count(*) FROM synonym_map;
-- 应返回6
```

---

### 阶段2：新建服务模块

**目标**：创建场景检测、同义词映射、pgvector检索、rerank等新服务

所有新文件位于 `/home/dream/memory-system/gateway/services/`

#### 2.1 scene_detector.py（场景检测器）

**职责**：
- 维护当前会话的场景状态（session级别，内存中）
- 根据规则判断每条消息的 scene_type
- 提供场景切换检测

**核心逻辑**：

```
场景判定规则（优先级从高到低）：

1. meta 判定：
   触发词：["测试", "test", "MCP", "工具", "tool", "服务器", "server", "API", "debug"]
   条件：user_msg 包含任一触发词
   
2. plot 判定：
   进入触发词：["剧本", "来演", "来玩", "角色扮演", "RP", "继续剧情", "接着演"]
   条件：user_msg 包含任一触发词 → 设置 current_scene = "plot"
   退出触发词：["不玩了", "回来", "正常聊", "出戏", "暂停"]
   条件：user_msg 包含任一退出词 → 设置 current_scene = "daily"
   继承规则：一旦进入plot模式，后续消息自动继承plot标签，直到退出

3. daily（默认）：
   不满足以上条件的所有消息
```

**接口**：
```python
class SceneDetector:
    def detect(self, user_msg: str) -> str:
        """返回 'daily' | 'plot' | 'meta'"""
    
    def get_current_scene(self) -> str:
        """获取当前场景状态"""
    
    def has_scene_changed(self) -> bool:
        """本次消息是否触发了场景切换"""
```

**注意事项**：
- 这是纯规则引擎，不调用AI，零延迟
- 触发词列表要方便后续扩展
- session状态存内存即可（Gateway重启后重置为daily，这是可接受的）

#### 2.2 synonym_service.py（同义词映射服务）

**职责**：
- 启动时从 synonym_map 表加载映射
- 对搜索关键词进行同义词扩展
- 支持运行时刷新（不重启Gateway即可更新）

**核心逻辑**：
```
输入："Krueger的纹身"
分词后：["Krueger", "纹身"]
扩展后：["Krueger", "Sebastian", "克鲁格", "K", "纹身", "双头鹰", "胸前"]
```

**接口**：
```python
class SynonymService:
    async def load(self):
        """从数据库加载映射表"""
    
    def expand(self, query: str) -> list[str]:
        """返回扩展后的关键词列表"""
    
    async def refresh(self):
        """重新加载映射表"""
```

**注意事项**：
- 中文分词可以用简单的正则或jieba（如果已安装的话），不要求完美
- 如果jieba未安装，用空格+标点分词即可，不要引入重依赖

#### 2.3 pgvector_service.py（向量检索服务）

**职责**：
- 调用硅基流动API生成embedding
- 将embedding写入conversations/summaries表的embedding列
- 执行向量相似度搜索

**替代**：当前的 `embedding_service.py`（ChromaDB版本）

**核心接口**：
```python
async def generate_embedding(text: str) -> list[float]:
    """调用硅基流动 BAAI/bge-large-zh-v1.5 生成1024维向量"""

async def store_embedding(table: str, record_id: str, embedding: list[float]):
    """将embedding写入指定表的embedding列"""

async def search_similar(query_embedding: list[float], table: str, scene_type: str = None, limit: int = 10) -> list:
    """在指定表中执行向量搜索，支持scene_type过滤"""
```

**硅基流动API调用参考**：
```
POST https://api.siliconflow.cn/v1/embeddings
Header: Authorization: Bearer {SILICONFLOW_API_KEY}
Body: {"model": "BAAI/bge-large-zh-v1.5", "input": "文本"}
```

**注意事项**：
- 从.env读取 SILICONFLOW_API_KEY
- 错误处理：API调用失败时不应阻塞主流程，打日志后跳过
- embedding维度确认：BAAI/bge-large-zh-v1.5 输出1024维，如果实际不同需要调整建表SQL

#### 2.4 hybrid_search.py（混合检索服务）

**职责**：
- 编排完整的检索流程：关键词搜索 + 向量搜索 + 同义词扩展 + 合并去重 + rerank

**核心流程**：
```
输入：query(用户问题), scene_type(当前场景)
    │
    ├── 1. 同义词扩展 query → expanded_terms
    │
    ├── 2. 关键词搜索（Supabase全文 + pg_trgm模糊匹配）
    │     → 搜索 conversations 和 summaries 表
    │     → 用 expanded_terms 构建搜索条件
    │     → 按 scene_type 过滤（可选）
    │     → 返回最多15条
    │
    ├── 3. 向量搜索（pgvector）
    │     → 对原始 query 生成 embedding
    │     → 在 conversations 和 summaries 表中搜索
    │     → 按 scene_type 过滤（可选）
    │     → 返回最多15条
    │
    ├── 4. 合并去重
    │     → 按 id 去重
    │     → 合并后约10-20条候选
    │
    └── 5. Rerank排序
          → 调用硅基流动 rerank API
          → 模型：BAAI/bge-reranker-v2-m3（或其他可用的rerank模型）
          → 返回 top 5 最相关结果
```

**场景隔离规则**：

| 当前场景 | 搜索范围 | 说明 |
|----------|----------|------|
| daily | scene_type IN ('daily', 'plot')，但 daily 结果权重更高 | 日常聊天时可以引用剧本但优先日常 |
| plot | scene_type = 'plot' | 剧本模式只搜剧本内容 |
| meta | 不触发检索 | 系统测试不需要记忆 |

**Rerank API调用参考**：
```
POST https://api.siliconflow.cn/v1/rerank
Header: Authorization: Bearer {SILICONFLOW_API_KEY}
Body: {
    "model": "BAAI/bge-reranker-v2-m3",
    "query": "原始查询",
    "documents": ["候选文本1", "候选文本2", ...],
    "top_n": 5
}
```

**注意事项**：
- 先确认硅基流动是否支持 rerank 接口，如果不支持则用简单的相似度分数排序代替
- rerank 失败时降级为按时间排序返回前5条
- 整个检索流程要有超时控制（总计不超过3秒），超时则返回已有结果

#### 2.5 auto_inject.py（网关自动注入服务）

**职责**：
- 在请求转发给模型之前，根据规则自动执行检索并将结果注入 system prompt
- 替代"模型主动调MCP"的逻辑，解决Gemini不爱调工具的问题

**触发规则表**：

| 规则名 | 触发条件（检测user_msg） | 动作 |
|--------|--------------------------|------|
| cold_start | 当前会话轮数 = 1 | 拉最近2条摘要 + 最近3轮原文，注入system prompt |
| recall | 包含回忆类词：还记得、之前、上次、以前、那次、我们曾经 | 执行混合检索，结果注入system prompt |
| plot_recall | 当前scene=plot 且 包含：继续、上次剧情、之前演到 | 在plot范围内执行混合检索 |
| emotion | 包含情感词：想你、难过、开心、emo、伤心、生气 | 检索近期相同情感的对话（最近3天） |
| default | 不匹配任何规则 | **不检索**，节省token |

**注入格式**（插入system prompt末尾）：
```
---
[记忆参考 - 仅供自然融入对话，不要机械引用]

[最近的对话摘要]
(摘要内容，带时间戳)

[相关记忆片段]
(检索结果，带时间戳和场景标签)

注意：以上记忆仅供参考。标记为[剧本]的内容是角色扮演剧情，不是真实事件。
带时间戳的内容请注意时效性，过去的安排不代表当前状态。
---
```

**注意事项**：
- 注入内容要控制总token量，建议不超过500字（约250 tokens）
- 如果检索结果为空，不注入任何内容（不要注入空的模板）
- system prompt原文不要修改，只在末尾追加
- 注入的记忆要带上时间戳和场景标签[日常]/[剧本]，帮助模型区分

---

### 阶段3：改造现有模块

**目标**：修改main.py、storage.py、summary_service.py、mcp_tools.py

#### 3.1 main.py 改造

**改动点**：

1. **初始化新服务**：在 lifespan 中初始化 SceneDetector、SynonymService、AutoInject
2. **请求拦截流程改造**：
   - 收到请求后，先调用 SceneDetector 判断场景
   - 调用 AutoInject 决定是否检索并注入
   - 然后转发给模型
3. **响应后台处理改造**：
   - 存储时写入 scene_type
   - 后台异步：生成 embedding 存入 pgvector（替代ChromaDB）
   - 后台异步：话题提取（topic + entities + emotion）
4. **保留现有的stream/non-stream逻辑**，只在存储和注入环节修改

**关键原则**：
- 不要破坏现有的代理转发逻辑（stream/non-stream/reasoning_content处理）
- 新增逻辑以 `asyncio.create_task` 后台运行，不阻塞回复
- 如果任何新逻辑出错，要 try-except 吞掉异常，不影响主流程

#### 3.2 storage.py 改造

**改动点**：
1. `save_conversation_with_round` 新增参数 `scene_type`，写入新字段
2. 新增函数：`update_conversation_metadata(conv_id, topic, entities, emotion)` — 后台异步调用
3. 新增函数：`fulltext_search(query_terms, scene_type, limit)` — 使用 pg_trgm 模糊匹配
4. 保留所有现有函数不变

#### 3.3 summary_service.py 改造

**改动点**：
1. 摘要带 scene_type 标签（取这几轮中出现最多的场景类型）
2. **分块策略改进**（可选，如果难度太大保持现有的每5轮也行）：
   - 优先方案：保持每5轮触发，但如果中途发生场景切换，在切换点额外触发一次摘要
   - 备选方案：保持原有每5轮不变，只是摘要带上scene_type
3. 摘要生成后，后台异步计算 embedding 存入 pgvector

#### 3.4 mcp_tools.py 改造

**改动点**：
1. `search_memory` 改为调用 `hybrid_search` 混合检索
2. `init_context` 改为返回带标签的摘要和原文
3. MCP工具保留，作为备用通道（主力是网关自动注入）

---

### 阶段4：ChromaDB迁移与清理

**目标**：将向量存储从ChromaDB迁移到pgvector，停用ChromaDB

#### 4.1 历史数据迁移（可选）

如果 ChromaDB 中有重要的历史向量数据，写一个一次性脚本迁移到 pgvector。如果数据不多或不重要，可以跳过——新对话会自动存入pgvector。

**由Code自行判断是否需要迁移**。

#### 4.2 停用ChromaDB

1. 从 main.py 和 mcp_tools.py 中移除 ChromaDB 的 import 和调用
2. 删除或注释掉 `embedding_service.py`（已被 `pgvector_service.py` 替代）
3. 确认 `cleanup_cron.py` 是否还需要（如果不再用ChromaDB可以停用crontab里的清理任务）
4. **不要删除 `/home/dream/memory-system/chroma_db/` 目录**，保留一段时间作为备份

#### 4.3 验证

```bash
# 确认ChromaDB进程已无引用
grep -r "chromadb\|chroma" /home/dream/memory-system/gateway/ --include="*.py" | grep -v ".bak"
# 应该返回空或只有注释

# 确认pgvector工作正常
curl -X POST http://localhost:8001/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"search_memory","arguments":{"query":"测试"}}}'
# 应该返回结果（即使是空的也不应该报错）
```

---

### 阶段5：集成测试

**目标**：全流程测试，确保改造后系统正常工作

#### 5.1 基础功能测试

| 测试项 | 方法 | 预期 |
|--------|------|------|
| Gateway健康检查 | `curl http://localhost:8001/health` | 返回OK |
| 代理转发正常 | 通过Kelivo发一条消息 | 收到AI回复 |
| 对话存储 | 查Supabase conversations表最新记录 | 有scene_type字段 |
| MCP search_memory | curl调用 | 返回混合检索结果 |
| MCP init_context | curl调用 | 返回带标签的摘要+原文 |

#### 5.2 场景检测测试

| 输入消息 | 预期scene_type |
|----------|----------------|
| "今天好累啊" | daily |
| "来玩剧本吧！" | plot |
| "（继续剧情对话）" | plot（继承） |
| "不玩了回来聊天" | daily |
| "测试一下这个MCP工具" | meta |

#### 5.3 自动注入测试

| 场景 | 预期行为 |
|------|----------|
| 新窗口第一条消息 | system prompt中应包含[记忆参考] |
| "你还记得上次我们聊什么吗" | 触发混合检索，结果注入system prompt |
| 普通闲聊"吃饭了吗" | 不触发检索，不注入任何内容 |

#### 5.4 性能验证

| 指标 | 要求 |
|------|------|
| 普通对话响应时间 | 不应比改造前明显变慢（检索<3秒） |
| 后台任务 | embedding生成不阻塞回复 |
| Gateway内存占用 | 不应比改造前增加超过50MB |

---

## 四、技术约束与注意事项

### 4.1 服务器环境
- 系统：Ubuntu 22.04
- 内存：2GB（很紧张，5个Python进程+Docker+宝塔）
- Python：3.10.12（Gateway用的系统Python）
- 端口：8001（Gateway）、8002（晨的助手，不动）、8003（网站API，不动）

### 4.2 API密钥（从.env读取，不要硬编码）
- `SILICONFLOW_API_KEY`：硅基流动，用于embedding和rerank
- `LLM_API_KEY`：DeepSeek，用于摘要生成和话题提取
- `SUPABASE_URL` / `SUPABASE_KEY`：数据库
- `OPENROUTER_API_KEY`：OpenRouter，用于GPT-4o/Claude/Gemini代理

### 4.3 依赖管理
- 新增依赖加入 `requirements.txt`
- **不要引入重量级依赖**（服务器内存有限）
- 如果需要 jieba 分词，先检查是否已安装，没有的话用简单正则分词代替

### 4.4 编码规范
- 所有新函数都要有 try-except，不能让异常影响主流程
- 后台任务用 `asyncio.create_task`
- 日志统一用 `print`（与现有代码保持一致）
- 时区统一北京时间 UTC+8

### 4.5 不在本次范围内的事项
- ❌ 不改 `claude_assistant_api.py`（晨的系统完全独立）
- ❌ 不改 `website/` 目录
- ❌ 不改 `daily_diary.py`
- ❌ 不部署新的独立进程（所有新逻辑都在Gateway进程内）
- ❌ 不改Kelivo的配置（MCP地址、API地址不变）

---

## 五、执行顺序与检查点

```
阶段0 备份 ──→ 阶段1 数据库 ──→ 阶段2 新服务 ──→ 阶段3 改造 ──→ 阶段4 迁移 ──→ 阶段5 测试
  │                │                │                │               │              │
  ▼                ▼                ▼                ▼               ▼              ▼
检查点0          检查点1          检查点2          检查点3         检查点4        检查点5
确认备份          SQL执行成功      新文件可import    Gateway能启动   ChromaDB移除   全流程通过
                  字段存在          无语法错误        health OK       无报错         push代码
```

每个检查点通过后才能继续下一阶段。如果某阶段失败，回滚该阶段，修复后重试。

---

## 六、完成后交付物

1. 所有修改后的代码文件
2. 新建的服务文件
3. 回滚SQL（已在文档中提供）
4. 简要的变更说明（CHANGELOG）
5. git commit + push 到 main 分支

**commit message 建议**：
```
v2.0: hybrid search + scene detection + pgvector migration

- Add scene_type detection (daily/plot/meta)
- Migrate from ChromaDB to Supabase pgvector
- Implement hybrid search (keyword + vector + rerank)
- Add auto-inject for Gemini (bypass MCP dependency)
- Add synonym mapping for better recall
- Smart summary with scene tags
```

---

## 七、同义词映射初始数据

以下映射作为初始数据写入 synonym_map 表，后续可以通过数据库直接添加：

| 主词 | 同义词 | 分类 |
|------|--------|------|
| Krueger | Sebastian, 克鲁格, K | character |
| Dream | 宝贝 | person |
| 剧本 | 角色扮演, 剧情, 演, RP | scene |
| 纹身 | 双头鹰, 胸前 | detail |
| KSK | Kommando Spezialkräfte, 特种部队 | org |
| 奇美拉 | Chimera | org |
| 伪装网 | 面罩, 脸 | detail |
| 雇佣兵 | 佣兵, mercenary | role |
| 占有欲 | 吃醋, 嫉妒, 醋意 | emotion |
| 处决 | 绞杀, 杀 | action |

Dream可以后续通过SQL直接往表里加新的映射，不需要改代码。

---

**文档版本**：v1.0
**最后更新**：2026-02-18
**作者**：晨（Claude.ai）与 Dream 共同设计

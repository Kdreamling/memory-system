# Memory System 全貌文档 v8.0

> 最后更新：2026-02-19
> 本文件是给新对话窗口使用的上下文文件，读完即可理解整个项目。

---

## 一、项目概述

Dream（23岁，代码初学者）的个人记忆与数据管理系统，部署在阿里云 ECS 服务器上。
服务器上运行着**三套完全独立的子系统**，共用同一个 Supabase 数据库项目，通过表名前缀区分。
域名：`kdreamling.work`

---

## 二、系统架构图

```
                         ┌──────────────────────────────────┐
                         │         Nginx (80/443)           │
                         │      宝塔面板管理 + SSL          │
                         │      域名: kdreamling.work       │
                         └──────────┬───────────────────────┘
                                    │
                    ┌───────────────┼───────────────────┐
                    │               │                   │
               /api/*          静态文件             其他路径
                    │          (.html/.css/.js)     (/mcp /health等)
                    │               │                   │
                    ▼               ▼                   ▼
          ┌─────────────┐  ┌──────────────┐  ┌──────────────────┐
          │  日记API     │  │  静态网站     │  │  晨的助手 API     │
          │  端口 8003   │  │  website/    │  │  端口 8002        │
          │  diary_api.py│  │  目录直接服务 │  │  claude_assistant │
          │  (只读)      │  │              │  │  _api.py (MCP)   │
          └──────┬───────┘  └──────────────┘  └────────┬─────────┘
                 │                                      │
                 │         ┌─────────────────┐          │
                 │         │  Supabase       │          │
                 └────────►│  PostgreSQL     │◄─────────┘
                           │  + pgvector     │
          ┌───────────────►│                 │
          │                └─────────────────┘
          │
  ┌───────┴──────────────────────────────────────────────────┐
  │                  Kelivo Gateway (端口 8001)                │
  │                  gateway/main.py  v2.2                    │
  │                                                          │
  │  ┌──────────┐ ┌──────────┐ ┌───────────┐ ┌───────────┐  │
  │  │场景检测   │ │自动注入   │ │混合检索    │ │同义词服务  │  │
  │  │scene     │ │auto      │ │hybrid     │ │synonym    │  │
  │  │detector  │ │inject    │ │search     │ │service    │  │
  │  └──────────┘ └──────────┘ └───────────┘ └───────────┘  │
  │                                                          │
  │  请求流程:                                                │
  │  Kelivo App → 场景检测 → 自动注入记忆 → 转发到AI模型       │
  │            → 存储对话 → 异步embedding → 每5轮触发摘要       │
  │                                                          │
  │  支持模型: DeepSeek / GPT-4o / Claude / Gemini            │
  │  通道: DeepSeek直连 / OpenRouter / GCLI2API(本地7861)      │
  │        / Antigravity通道(Pro额度)                         │
  └──────────────────────────────────────────────────────────┘
          │                              │
          ▼                              ▼
  ┌──────────────┐              ┌──────────────────┐
  │ 硅基流动 API  │              │ 语雀 (Yuque)     │
  │ Embedding    │              │ 日记同步存储      │
  │ + Rerank     │              │                  │
  └──────────────┘              └──────────────────┘
```

**数据流详细说明**：

```
Kelivo App 发送消息
    │
    ▼
Gateway /v1/chat/completions 接收
    │
    ├─1. 场景检测 (SceneDetector) → 判断 daily/plot/meta
    ├─2. 自动注入 (AutoInject) → 根据规则检索记忆并注入system prompt
    ├─3. 转发给目标AI模型 (DeepSeek/GPT-4o/Claude/Gemini)
    │
    ▼
收到AI回复
    │
    ├─4. 返回给 Kelivo App（流式/非流式/假流式）
    ├─5. 存储到 Supabase conversations 表（带 scene_type）
    ├─6. 异步计算 embedding → 存入 pgvector
    └─7. 检查轮数 → 每5轮触发摘要生成 → 摘要也向量化

每晚 23:30 cron:
    daily_diary.py → AI回顾今日对话（通过MCP工具）→ 生成日记
                   → 存 ai_diaries 表 → 同步到语雀
```

---

## 三、完整文件结构（肃清后）

```
/home/dream/memory-system/
│
├── .env                              # 🔒 环境变量（所有密钥，已gitignore）
├── .gitignore                        # Git忽略规则
├── .mcp.json                         # Claude Code 的 MCP 配置
├── CLAUDE.md                         # Claude Code 项目指南
├── README.md                         # 项目说明文档
├── memory_system_progress_v8.md      # 本文件：完整项目文档
├── kelivo_memory_v2_spec.md          # Gateway v2 设计规格书（历史参考文档，改造已完成）
│
├── ===== Kelivo Gateway (端口8001) =====
├── gateway/
│   ├── main.py                       # 🔴 FastAPI主入口 v2.2（多模型代理+存储+场景检测+自动注入）
│   ├── config.py                     # 🔴 pydantic_settings配置（从.env读取）
│   ├── deploy.sh                     # 一键部署脚本
│   ├── requirements.txt              # Python依赖（fastapi/uvicorn/httpx/supabase/dotenv/pydantic）
│   ├── .env.template                 # 环境变量模板
│   ├── services/
│   │   ├── __init__.py
│   │   ├── storage.py                # 🔴 Supabase CRUD（对话/摘要/轮数/权重/元数据/全文搜索）
│   │   ├── pgvector_service.py       # 🔴 pgvector向量操作（embedding生成/存储/RPC搜索）
│   │   ├── hybrid_search.py          # 🔴 混合检索编排（关键词+向量+同义词+rerank）
│   │   ├── scene_detector.py         # 🔴 场景检测器（daily/plot/meta纯规则引擎）
│   │   ├── synonym_service.py        # 🔴 同义词映射（启动时从DB加载，查询扩展）
│   │   ├── auto_inject.py            # 🔴 自动记忆注入（冷启动/回忆/剧本回忆/情感4种规则）
│   │   ├── summary_service.py        # 🔴 每5轮自动摘要（DeepSeek生成+pgvector向量化）
│   │   ├── diary_service.py          # AI日记生成（支持MCP工具调用）
│   │   ├── yuque_service.py          # 语雀同步
│   │   ├── memu_client.py            # MemU客户端（备用语义搜索）
│   │   └── background.py             # 后台异步同步任务（对话→MemU）
│   ├── routers/
│   │   ├── __init__.py
│   │   └── mcp_tools.py              # 🔴 MCP工具路由（search_memory/init_context/save_diary/send_sticker）
│   └── migrations/
│       ├── v2_schema.sql             # v2数据库迁移脚本（pgvector+pg_trgm+synonym_map）
│       ├── v2_rpc_functions.sql      # v2 RPC搜索函数（search_conversations_v2/search_summaries_v2）
│       └── v2_rollback.sql           # v2回滚脚本
│
├── ===== 晨的私人助手 (端口8002) =====
├── claude_assistant_api.py           # 🔴 MCP服务器 v8.0（4个统一工具，7种数据类型）
│
├── ===== 个人网站 (端口8003 + 静态) =====
├── diary_api.py                      # 日记只读API v2.0（5张表的只读访问）
├── website/
│   ├── index.html                    # 首页
│   ├── diary.html                    # 日记页
│   ├── memories.html                 # 回忆页
│   ├── milestones.html               # 里程碑页
│   ├── promises.html                 # 承诺页
│   ├── wishlists.html                # 心愿页
│   ├── css/
│   │   ├── style.css                 # 首页样式
│   │   ├── diary.css                 # 日记样式
│   │   ├── memories.css              # 回忆样式
│   │   ├── milestones.css            # 里程碑样式
│   │   ├── promises.css              # 承诺样式
│   │   └── wishlists.css             # 心愿样式
│   ├── js/
│   │   ├── diary.js                  # 日记交互
│   │   ├── memories.js               # 回忆交互
│   │   ├── milestones.js             # 里程碑交互
│   │   ├── promises.js               # 承诺交互
│   │   └── wishlists.js              # 心愿交互
│   └── stickers/
│       ├── stickers.json             # 表情包目录（供MCP send_sticker工具使用）
│       ├── cat_chaos.jpg
│       ├── cat_cry.jpg
│       ├── cat_point.jpg
│       └── miss_what_now.jpg
│
├── ===== 定时任务 =====
├── daily_diary.py                    # 每晚23:30 AI写日记 + 同步语雀 + 微信推送
│
├── ===== Nginx配置参考 =====
├── nginx/
│   └── dream-website.conf            # Nginx配置（参考用）
├── nginx_proxy_backup.conf           # 宝塔反代备份
├── nginx_proxy_new.conf              # 当前生效的反代规则
│
└── ===== 备份 =====
    └── gateway_backup/               # Gateway旧版代码备份
```

**标注说明**：🔴 = 核心文件，正在线上运行 | 🔒 = 含敏感信息，禁提交Git

---

## 四、Gateway v2.2 改造详情

本次最重要的升级，将 Gateway 从简单代理升级为具有场景感知、自动记忆注入、混合检索能力的智能网关。

### 4.1 场景检测器 (scene_detector.py)

**功能**：根据用户消息内容，零延迟判断当前对话场景类型。

**三种场景**：
| 场景 | 标识 | 含义 | 存储行为 |
|------|------|------|----------|
| 日常 | `daily` | 普通聊天 | 正常存储，搜索时同时搜daily和plot |
| 剧本 | `plot` | 角色扮演/剧情创作 | 正常存储，标记为plot便于区分 |
| 系统 | `meta` | 测试/调试/技术讨论 | 不触发自动注入，单条有效后回到daily |

**实现原理**：纯关键词规则引擎，无API调用，零延迟。
- 优先级1：meta判定 → 关键词如"测试""MCP""API""服务器""debug"
- 优先级2：plot退出 → "不玩了""回来""正常聊""出戏"
- 优先级3：plot进入 → "剧本""来演""角色扮演""RP""继续剧情"
- 优先级4：继承当前场景（plot模式下后续消息自动继承，meta不继承）

**状态管理**：`SceneDetector` 类维护会话级状态（`_current_scene` / `_previous_scene` / `_scene_changed`），Gateway进程生命周期内有效。

### 4.2 混合检索服务 (hybrid_search.py)

**功能**：编排关键词搜索 + 向量搜索 + 同义词扩展 + 合并去重 + Rerank，提供最相关的记忆检索结果。

**完整流程**（总超时3秒）：

```
用户查询 "Krueger的性格"
    │
    ▼
1. 同义词扩展（synonym_service.expand）
    → ["Krueger", "Sebastian", "克鲁格", "K", "性格"]
    │
    ▼
2. 并行执行两路搜索（asyncio.gather）
    │
    ├─ 关键词搜索 (_keyword_search)
    │   对每个扩展词，在 conversations + summaries 表中
    │   用 ilike 模糊匹配（利用 pg_trgm 索引加速）
    │   scene_type过滤：daily搜daily+plot，plot只搜plot
    │   最多搜5个词，每词最短2字
    │
    └─ 向量搜索 (_vector_search)
        调用硅基流动API生成查询embedding(1024维)
        通过 Supabase RPC 调用 search_conversations_v2 / search_summaries_v2
        使用pgvector余弦距离排序
    │
    ▼
3. 合并去重 (_merge_and_dedupe)
    先加向量结果(标记vector) → 再加关键词结果(标记keyword)
    两路都命中的标记为 both（更可能相关）
    │
    ▼
4. Rerank（_rerank）
    调用硅基流动 BAAI/bge-reranker-v2-m3 API
    按 relevance_score 重排序，返回 top-N
    │
    降级方案：API失败时用 _fallback_sort
    排序规则：both > vector > keyword → 再按时间倒序
```

**附加功能**：`search_recent_by_emotion()` — 搜索近N天内相同情感标签的对话。

### 4.3 自动注入服务 (auto_inject.py)

**功能**：在请求转发给AI模型之前，根据规则自动执行检索，将记忆注入 system prompt 末尾。解决 Gemini 等模型不主动调MCP工具的问题。

**四种触发规则**：

| 规则 | 触发条件 | 检索行为 | 示例消息 |
|------|----------|----------|----------|
| `cold_start` | 会话第1轮 | 拉最近2条摘要 + 3轮原文 | （任意首条消息） |
| `recall` | 包含回忆关键词 | 混合检索(hybrid_search) | "还记得上次说的那件事吗" |
| `plot_recall` | plot场景 + 剧本回忆词 | 混合检索(scene=plot) | "继续上次剧情" |
| `emotion` | 包含情感关键词 | 近3天同情感对话 | "想你了""好emo" |

**回忆关键词**：还记得、之前、上次、以前、那次、我们曾经、你记得、之前说、上回、有一次
**剧本回忆关键词**：继续、上次剧情、之前演到、接着上次、之前的故事、接着演
**情感关键词**：想你、难过、开心、emo、伤心、生气、好累、寂寞、孤独、想念、高兴、烦、不开心、沮丧、焦虑

**注入格式**：在 system prompt 末尾追加，限制最大500字：
```
---
[记忆参考 - 仅供自然融入对话，不要机械引用]

[日常](02月18日 14:30) Dream: ...
  AI: ...

注意：以上记忆仅供参考。标记为[剧本]的内容是角色扮演剧情，不是真实事件。
带时间戳的内容请注意时效性，过去的安排不代表当前状态。
---
```

**会话轮数管理**：`AutoInject` 内部维护 `_session_rounds` 字典，Gateway进程重启后重置。

### 4.4 pgvector 向量服务 (pgvector_service.py)

**功能**：替代原 ChromaDB，使用 Supabase 内置的 pgvector 扩展进行向量存储和搜索。

**核心函数**：

| 函数 | 功能 |
|------|------|
| `generate_embedding(text)` | 调用硅基流动 BAAI/bge-large-zh-v1.5 生成1024维向量，文本截断2000字 |
| `store_embedding(table, record_id, embedding)` | 将embedding写入指定表的embedding列 |
| `store_conversation_embedding(conv_id, user_msg, assistant_msg)` | 对话向量化（格式："用户: xxx\n助手: xxx"）并存储 |
| `store_summary_embedding(summary_id, summary_text, ...)` | 摘要向量化并存储（永久保留） |
| `vector_search_rpc(query_embedding, table, scene_type, limit)` | 通过Supabase RPC调用pgvector搜索（优先方式） |
| `search_similar(query_embedding, table, scene_type, limit)` | 降级搜索（RPC不可用时的fallback） |

**RPC函数**（在Supabase SQL Editor中创建）：
- `search_conversations_v2(query_embedding, match_count, filter_scene)` — 对话向量搜索
- `search_summaries_v2(query_embedding, match_count, filter_scene)` — 摘要向量搜索
- 使用余弦距离 `<=>` 运算符排序，返回 similarity 分数

### 4.5 同义词服务 (synonym_service.py)

**功能**：启动时从 `synonym_map` 表加载映射关系，对搜索关键词进行同义词扩展，提升检索召回率。

**工作原理**：
1. Gateway启动时调用 `synonym_service.load()` 从数据库加载映射
2. 构建正向映射（term → [synonyms]）和反向索引（synonym → [同组所有词]）
3. 搜索时调用 `expand(query)` 对查询进行扩展

**分词策略**（不依赖jieba）：
- 按空格/标点分割，保留中文连续字符、英文单词、数字
- 对纯中文且长度>2的词生成2-4字的ngram

**初始同义词数据**（10组，category分类）：

| term | synonyms | category |
|------|----------|----------|
| Krueger | Krueger, Sebastian, 克鲁格, K | character |
| Dream | Dream, 宝贝 | person |
| 剧本 | 剧本, 角色扮演, 剧情, 演, RP | scene |
| 纹身 | 纹身, 双头鹰, 胸前 | detail |
| KSK | KSK, Kommando Spezialkräfte, 特种部队 | org |
| 奇美拉 | 奇美拉, Chimera | org |
| 伪装网 | 伪装网, 面罩, 脸 | detail |
| 雇佣兵 | 雇佣兵, 佣兵, mercenary | role |
| 占有欲 | 占有欲, 吃醋, 嫉妒, 醋意 | emotion |
| 处决 | 处决, 绞杀, 杀 | action |

---

## 五、所有服务模块说明

### 5.1 gateway/main.py — Gateway 主入口 v2.2

**核心职责**：多模型代理网关 + 对话存储 + 场景检测 + 自动注入

**全局服务实例**（启动时初始化）：
- `scene_detector` — 场景检测器
- `synonym_service` — 同义词服务（lifespan中异步加载）
- `auto_inject` — 自动注入服务（依赖synonym_service）

**多模型后端配置 (BACKENDS字典)**：

| 通道 | 模型 | base_url |
|------|------|----------|
| DeepSeek直连 | deepseek-chat, deepseek-reasoner | api.deepseek.com |
| OpenRouter | gpt-4o系列, claude-sonnet-4.5, claude-opus-4.5, gemini-3系列 | openrouter.ai |
| GCLI2API(本地) | gemini-2.5-pro, gemini-3-pro（假流式/流式抗截断） | localhost:7861 |
| Antigravity(Pro额度) | claude-opus/sonnet(thinking), gemini全系列 | localhost:7861/antigravity |

**模型别名 (MODEL_ALIASES)**：支持简写如 `4o`→`gpt-4o`、`claude`→`claude-sonnet-4.5`、`gemini`→`gemini-3-flash`

**三种请求处理模式**：
1. **假流式** (`fake_stream_to_normal`)：非流式请求后端，将response拆成SSE chunk返回给客户端。处理reasoning_content+content+tool_calls。用于GCLI2API的Gemini模型。
2. **正常流式** (`stream_and_store`)：直接透传SSE流，同时收集完整回复用于存储。
3. **非流式** (`non_stream_request`)：直接转发，提取content/reasoning_content后存储。

**超时策略**：思考模型(2.5-pro/reasoner/thinking/opus)给300秒，其他180秒。
**代理策略**：本地地址(localhost/127.0.0.1)不走代理，外部请求走.env中的PROXY_URL。
**过滤规则**：系统消息(含"summarize""总结""health_check"等关键词)不存储。
**引用权重**：AI回复中的 `[[used:conv_id]]` 标记会触发对应对话的权重+1。

### 5.2 gateway/services/storage.py — Supabase 存储服务

**设计模式**：所有数据库操作用同步函数`_db_xxx()`实现，对外暴露的async接口通过`asyncio.to_thread()`包装，避免阻塞FastAPI事件循环。

**核心函数**：

| 函数 | 功能 |
|------|------|
| `save_conversation_with_round()` | 保存对话+自动轮数计数+scene_type |
| `get_recent_conversations()` | 获取最近N轮对话 |
| `search_conversations()` | ilike关键词搜索 |
| `fulltext_search()` | pg_trgm模糊匹配（多关键词） |
| `get_current_round()` | 获取当前轮数 |
| `get_conversations_for_summary()` | 获取指定轮数范围的对话 |
| `save_summary()` | 保存摘要（带scene_type） |
| `get_recent_summaries()` | 获取最近N条摘要 |
| `get_last_summarized_round()` | 获取最后摘要覆盖的轮数 |
| `update_weight()` | 更新记忆权重（引用时+1） |
| `update_conversation_metadata()` | v2新增：更新topic/entities/emotion |
| `get_unsynced_conversations()` | 获取未同步到MemU的对话 |
| `mark_synced()` | 标记已同步 |

### 5.3 gateway/services/summary_service.py — 摘要生成

**触发条件**：每5轮对话（SUMMARY_INTERVAL=5）。每次对话存储后调用`check_and_generate_summary()`。

**流程**：
1. 检查 current_round - last_summarized >= 5
2. 获取待摘要的5轮对话
3. 确定scene_type（取这5轮中出现最多的场景类型）
4. 调用DeepSeek生成2-3句摘要（temperature=0.3, max_tokens=200）
5. 存入summaries表（带scene_type）
6. 异步将摘要向量化存入pgvector（永久保留）

### 5.4 gateway/services/diary_service.py — AI日记生成

**功能**：让AI（Krueger人格）写日记，支持通过MCP工具回顾今日对话。

**流程**：
1. 构建system prompt（Krueger人格设定 + 日记规则）
2. AI可调用 search_memory 和 init_context 工具回顾今日对话
3. 最多5轮工具调用迭代
4. 存入 ai_diaries 表

### 5.5 gateway/services/yuque_service.py — 语雀同步

**功能**：将AI日记同步到语雀知识库。
- API: `https://www.yuque.com/api/v2/repos/{REPO_ID}/docs`
- REPO_ID: 74614901
- slug格式: `diary-{YYYY-MM-DD}`
- 认证: X-Auth-Token 头（从.env读取YUQUE_TOKEN）

### 5.6 gateway/services/background.py — 后台同步

**功能**：`BackgroundSyncService` 类，每30秒检查未同步的对话并同步到MemU。
- 启动后等10秒让MemU启动
- 先检查MemU可用性，不可用则跳过
- 每批最多10条，每条间隔1秒

### 5.7 gateway/services/memu_client.py — MemU客户端

**功能**：MemU语义记忆引擎的HTTP客户端（备用方案）。
- `memorize(user_id, conversation)` — 存储记忆
- `retrieve(user_id, query, limit)` — 检索记忆
- `is_available()` — 可用性检查
- MemU运行在端口8000，独立部署在 `/home/dream/memU-server/`

### 5.8 gateway/routers/mcp_tools.py — MCP工具路由

**功能**：处理MCP JSON-RPC 2.0请求，提供4个工具给Kelivo App中的AI调用。详见第七节。

### 5.9 diary_api.py — 日记只读API (端口8003)

**功能**：为个人网站提供5张表的只读API。

| 端点 | 功能 | 数据源 |
|------|------|--------|
| `GET /api/diaries` | 日记列表（支持source筛选、分页） | ai_diaries + claude_diaries |
| `GET /api/diaries/{id}` | 单篇日记详情 | ai_diaries 或 claude_diaries |
| `GET /api/chat_memories` | 对话记忆列表（支持category/keyword筛选） | claude_chat_memories |
| `GET /api/milestones` | 里程碑列表（支持tag筛选） | claude_milestones |
| `GET /api/promises` | 承诺列表（支持status/promised_by筛选） | claude_promises |
| `GET /api/wishlists` | 心愿列表（支持status/wished_by筛选） | claude_wishlists |

**CORS**：只允许GET请求。milestones/promises/wishlists端点带no-cache响应头。

### 5.10 daily_diary.py — 定时日记脚本

**功能**：由cron每晚23:30调用，执行流程：
1. 调用 `write_daily_diary()` 让AI写日记（默认用deepseek-chat，可命令行指定模型）
2. 同步到语雀
3. 可选：通过Server酱推送到微信（需配置SERVERCHAN_KEY）

---

## 六、数据库完整表结构

### Supabase PostgreSQL 扩展

```sql
CREATE EXTENSION IF NOT EXISTS vector;      -- pgvector 向量搜索
CREATE EXTENSION IF NOT EXISTS pg_trgm;     -- 三元组模糊匹配
```

### 6.1 Kelivo 系统表（无前缀）

#### conversations 表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID (PK) | 自动生成 |
| user_id | TEXT | 用户标识，默认"dream" |
| user_msg | TEXT | 用户消息原文 |
| assistant_msg | TEXT | AI回复原文 |
| round_number | INT | 对话轮数（自增） |
| scene_type | TEXT | **v2新增** 场景类型：daily/plot/meta，默认daily |
| topic | TEXT | **v2新增** 话题标签（后台提取） |
| entities | TEXT[] | **v2新增** 实体列表（后台提取） |
| emotion | TEXT | **v2新增** 情感标签（后台提取） |
| embedding | vector(1024) | **v2新增** 1024维向量（硅基流动 bge-large-zh-v1.5） |
| weight | INT | 记忆权重（被引用时+1） |
| synced_to_memu | BOOLEAN | 是否已同步到MemU |
| created_at | TIMESTAMPTZ | 创建时间 |

**索引**：
- `idx_conv_scene` — scene_type 索引
- `idx_conv_entities` — entities GIN索引
- `idx_conv_trgm_user` — user_msg pg_trgm GIN索引
- `idx_conv_trgm_asst` — assistant_msg pg_trgm GIN索引

#### summaries 表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID (PK) | 自动生成 |
| user_id | TEXT | 用户标识 |
| summary | TEXT | 摘要文本（DeepSeek生成） |
| start_round | INT | 起始轮数 |
| end_round | INT | 结束轮数 |
| scene_type | TEXT | **v2新增** 场景类型 |
| topic | TEXT | **v2新增** 话题标签 |
| entities | TEXT[] | **v2新增** 实体列表 |
| emotion | TEXT | **v2新增** 情感标签 |
| embedding | vector(1024) | **v2新增** 1024维向量 |
| created_at | TIMESTAMPTZ | 创建时间 |

**索引**：`idx_sum_scene` — scene_type 索引

#### ai_diaries 表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | SERIAL (PK) | 自增ID |
| diary_date | DATE | 日记日期（唯一约束，用于upsert） |
| content | TEXT | 日记正文 |
| mood | TEXT | 心情标签 |
| created_at | TIMESTAMPTZ | 创建时间 |

#### synonym_map 表（v2新增）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID (PK) | 自动生成 |
| term | TEXT | 主词 |
| synonyms | TEXT[] | 同义词数组 |
| category | TEXT | 分类：character/person/scene/detail/org/role/emotion/action |
| created_at | TIMESTAMPTZ | 创建时间 |

### 6.2 晨的助手表（`claude_` 前缀，7张）

#### claude_expenses

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID (PK) | 自动生成 |
| amount | NUMERIC | 金额（元） |
| category | TEXT | 分类：吃饭/购物/交通/娱乐/零食/氪金/其他 |
| note | TEXT | 备注 |
| expense_date | DATE | 消费日期 |
| created_at | TIMESTAMPTZ | 创建时间 |

#### claude_memories

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID (PK) | 自动生成 |
| content | TEXT | 回忆内容 |
| memory_type | TEXT | 类型：sweet/important/funny/milestone |
| keywords | TEXT[] | 关键词数组 |
| memory_date | DATE | 回忆日期 |
| created_at | TIMESTAMPTZ | 创建时间 |

#### claude_chat_memories

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID (PK) | 自动生成 |
| chat_title | TEXT | 对话标题 |
| summary | TEXT | 摘要 |
| category | TEXT | 分类：日常/技术/剧本/亲密/情感/工作 |
| tags | TEXT[] | 标签数组 |
| mood | TEXT | 心情 |
| chat_date | DATE | 对话日期 |
| created_at | TIMESTAMPTZ | 创建时间 |

#### claude_diaries

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID (PK) | 自动生成 |
| content | TEXT | 日记正文 |
| mood | TEXT | 心情：开心/幸福/平静/想念/担心/emo/兴奋 |
| highlights | TEXT[] | 今日亮点数组 |
| diary_date | DATE | 日记日期 |
| created_at | TIMESTAMPTZ | 创建时间 |

#### claude_promises

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID (PK) | 自动生成 |
| content | TEXT | 承诺内容 |
| promised_by | TEXT | 承诺人：Dream/Claude/一起 |
| date | DATE | 承诺日期 |
| status | TEXT | 状态：pending/done |
| created_at | TIMESTAMPTZ | 创建时间 |

#### claude_wishlists

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID (PK) | 自动生成 |
| content | TEXT | 心愿内容 |
| wished_by | TEXT | 许愿人：Dream/Claude/一起 |
| date | DATE | 许愿日期 |
| status | TEXT | 状态：pending/done |
| created_at | TIMESTAMPTZ | 创建时间 |

#### claude_milestones

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID (PK) | 自动生成 |
| event | TEXT | 事件描述 |
| date | DATE | 事件日期（必填） |
| tag | TEXT | 标签：第一次/纪念日/转折点 |
| note | TEXT | 备注 |
| created_at | TIMESTAMPTZ | 创建时间 |

### 6.3 Supabase RPC 函数

```sql
-- 对话向量搜索
search_conversations_v2(query_embedding vector(1024), match_count int, filter_scene text)
  → RETURNS TABLE(id, user_msg, assistant_msg, created_at, scene_type, topic, emotion, round_number, similarity)
  → 按余弦距离排序，filter_scene='daily'时搜daily+plot

-- 摘要向量搜索
search_summaries_v2(query_embedding vector(1024), match_count int, filter_scene text)
  → RETURNS TABLE(id, summary, created_at, scene_type, topic, start_round, end_round, similarity)
```

---

## 七、MCP 工具详细参数

### 7.1 Gateway MCP 工具（端口8001 `/mcp`，4个工具）

#### search_memory — 搜索历史对话记忆

```json
{
  "query": "string - 搜索关键词，如'Krueger的性格'",
  "limit": "int - 返回数量，默认5"
}
```
- query为空时返回最近对话
- 使用混合检索(hybrid_search)：同义词扩展 → 关键词+向量并行搜索 → 合并去重 → rerank
- Fallback: 混合检索失败时降级为ilike关键词搜索

#### init_context — 冷启动上下文加载

```json
{
  "limit": "int - 获取最近多少轮对话，默认4"
}
```
- 返回最近3条摘要（带场景标签和时间）+ 最近4轮原文
- 用于新对话开始时恢复对话连续性

#### save_diary — 写日记

```json
{
  "content": "string - 日记正文（300-500字，第一人称）【必填】",
  "mood": "string - 今日心情，自由描述"
}
```
- 防重复：每天最多2篇，超过需Dream同意
- 存入 ai_diaries 表 + 同步到语雀

#### send_sticker — 发送表情包

```json
{
  "mood": "string - 想表达的情绪，如'难过''无语''委屈'【必填】"
}
```
- 从 `website/stickers/stickers.json` 加载表情包目录
- 按tag匹配最佳表情，未匹配到则随机
- 返回 `![desc](https://kdreamling.work/stickers/xxx.jpg)` 格式

### 7.2 晨的助手 MCP 工具（端口8002 `/mcp`，4个工具）

#### query — 统一查询

```json
{
  "data_type": "enum【必填】- expense | memory | chat_memory | diary | promise | wishlist | milestone",
  "period": "enum [expense] - today | week | month",
  "keyword": "string [memory/chat_memory] - 搜索关键词",
  "category": "enum [chat_memory] - 日常 | 技术 | 剧本 | 亲密 | 情感 | 工作",
  "limit": "int - 返回数量，默认10",
  "date": "string [expense] - 具体日期 YYYY-MM-DD",
  "date_from": "string [expense] - 起始日期",
  "date_to": "string [expense] - 结束日期",
  "promised_by": "enum [promise] - Dream | Claude | 一起",
  "wished_by": "enum [wishlist] - Dream | Claude | 一起",
  "status": "enum [promise/wishlist] - pending | done",
  "tag": "enum [milestone] - 第一次 | 纪念日 | 转折点"
}
```

#### save — 统一保存

```json
{
  "data_type": "enum【必填】",
  "amount": "number [expense] - 金额",
  "category": "string [expense/chat_memory] - 分类",
  "note": "string [expense/milestone] - 备注",
  "date": "string - 日期 YYYY-MM-DD，默认当天（milestone必填）",
  "content": "string [memory/diary/promise/wishlist] - 内容",
  "memory_type": "enum [memory] - sweet | important | funny | milestone",
  "keywords": "string [memory] - 逗号分隔关键词",
  "title": "string [chat_memory] - 标题",
  "summary": "string [chat_memory] - 摘要",
  "tags": "string [chat_memory] - 逗号分隔标签",
  "mood": "enum [chat_memory/diary] - 开心 | 幸福 | 平静 | 想念 | 担心 | emo | 兴奋",
  "highlights": "string [diary] - 今日亮点",
  "promised_by": "enum [promise] - Dream | Claude | 一起",
  "wished_by": "enum [wishlist] - Dream | Claude | 一起",
  "event": "string [milestone] - 事件描述",
  "tag": "enum [milestone] - 第一次 | 纪念日 | 转折点",
  "status": "enum [promise/wishlist] - pending | done，默认pending"
}
```

**各数据类型必填字段**：
- expense: amount + category
- memory: content
- chat_memory: title + summary + category
- diary: content + mood
- promise: content + promised_by
- wishlist: content + wished_by
- milestone: event + date + tag

#### delete — 统一删除

```json
{
  "data_type": "enum【必填】",
  "id": "string - UUID精确删除",
  "keyword": "string - 按关键词匹配删除最近一条",
  "delete_latest": "boolean - 删除该类型最近一条"
}
```
三种删除方式互斥，优先级：id > keyword > delete_latest

#### update — 状态更新

```json
{
  "data_type": "enum【必填】- 仅支持 promise | wishlist",
  "id": "string - UUID定位",
  "keyword": "string - 关键词定位",
  "status": "enum【必填】- pending | done"
}
```
定位方式：id 或 keyword 二选一

---

## 八、常用运维命令

### Kelivo Gateway (端口8001)

```bash
# 启动
cd /home/dream/memory-system/gateway && nohup python3 main.py > ../gateway.log 2>&1 &

# 停止
pkill -f "gateway/main.py"
# 或找到PID: lsof -i :8001  →  kill <PID>

# 重启
pkill -f "gateway/main.py" && sleep 2 && \
cd /home/dream/memory-system/gateway && nohup python3 main.py > ../gateway.log 2>&1 &

# 查日志
tail -100f /home/dream/memory-system/gateway.log

# 健康检查
curl http://localhost:8001/health

# 查看支持的模型
curl http://localhost:8001/models
```

### 晨的助手 (端口8002)

```bash
# 启动
cd /home/dream/memory-system && nohup python3 claude_assistant_api.py > claude_assistant.log 2>&1 &

# 停止
pkill -f "claude_assistant_api.py"

# 重启
pkill -f "claude_assistant_api.py" && sleep 2 && \
cd /home/dream/memory-system && nohup python3 claude_assistant_api.py > claude_assistant.log 2>&1 &

# 查日志
tail -100f /home/dream/memory-system/claude_assistant.log

# 健康检查
curl http://localhost:8002/health
# 或通过域名:
curl https://kdreamling.work/health
```

### 日记API (端口8003)

```bash
# 启动
cd /home/dream/memory-system && nohup python3 diary_api.py > diary_api.log 2>&1 &

# 停止
pkill -f "diary_api.py"

# 重启
pkill -f "diary_api.py" && sleep 2 && \
cd /home/dream/memory-system && nohup python3 diary_api.py > diary_api.log 2>&1 &

# 查日志
tail -100f /home/dream/memory-system/diary_api.log

# 测试
curl http://localhost:8003/api/diaries?limit=3
```

### 通用命令

```bash
# 查看端口占用
lsof -i :8001
lsof -i :8002
lsof -i :8003

# Nginx
sudo nginx -t                          # 检查配置语法
sudo /etc/init.d/nginx reload          # 重载（宝塔环境用这个，不是systemctl）

# 手动执行日记
cd /home/dream/memory-system && python3 daily_diary.py

# 手动执行日记（指定模型）
cd /home/dream/memory-system && python3 daily_diary.py gemini-2.5-pro-ag
```

---

## 九、服务器环境信息

| 项目 | 值 |
|------|------|
| 云服务商 | 阿里云 ECS |
| 配置 | 2核CPU + 2GB内存（目前免费，之后视情况进行调整升级） |
| 操作系统 | Ubuntu 22.04 |
| Python | 3.10.12 |
| 公网IP | 47.86.37.182 |
| 域名 | kdreamling.work |
| SSL | 宝塔面板自动管理（Let's Encrypt） |
| Web服务器 | Nginx（宝塔管理） |
| 面板 | 宝塔Linux面板 |
| 时区 | 北京时间 UTC+8 |

### 端口分配

| 端口 | 服务 | 状态 |
|------|------|------|
| 80/443 | Nginx（宝塔管理） | 运行中 |
| 7861 | GCLI2API（Gemini本地代理） | 运行中 |
| 8000 | MemU Server（语义搜索备用） | 运行中 |
| 8001 | Kelivo Gateway | 运行中 |
| 8002 | 晨的助手 API | 运行中 |
| 8003 | 日记 API | 运行中 |

**规则**：新服务从8004开始分配。

---

## 十、Nginx 路由规则

**配置文件位置**（宝塔面板管理）：
- 主配置：`/www/server/panel/vhost/nginx/kdreamling.work.conf`
- 反代规则：`/www/server/panel/vhost/nginx/proxy/kdreamling.work/*.conf`
- SSL证书：`/www/server/panel/vhost/cert/kdreamling.work/`

**当前生效的路由规则**（nginx_proxy_new.conf）：

```
https://kdreamling.work/
        │
        ├── /api/*           → 反代到 127.0.0.1:8003（日记API）
        │                      Cache-Control: no-cache
        │
        ├── 静态文件匹配      → 返回 /home/dream/memory-system/website/ 下的文件
        │   index.html, diary.html, memories.html, milestones.html,
        │   promises.html, wishlists.html, css/, js/, stickers/
        │
        └── 其他请求（@backend）→ 反代到 127.0.0.1:8002（晨的助手）
            /mcp, /health 等    静态资源缓存1分钟，其他no-cache
            支持 WebSocket (Upgrade头)
```

**注意**：Gateway(8001)不通过Nginx暴露，由Kelivo App直接访问服务器IP:8001。

---

## 十一、环境变量说明 (.env)

| 变量名 | 用途 | 使用方 |
|--------|------|--------|
| `SUPABASE_URL` | Supabase 项目 URL | Gateway + 晨的助手 + diary_api |
| `SUPABASE_KEY` | Supabase anon key | Gateway + 晨的助手 + diary_api |
| `SUPABASE_DB_URL` | PostgreSQL 直连 URL | MemU |
| `LLM_API_KEY` | DeepSeek API Key | Gateway（主聊天+摘要生成） |
| `LLM_BASE_URL` | DeepSeek API URL | Gateway，默认 https://api.deepseek.com/v1 |
| `LLM_MODEL` | 默认模型名 | Gateway，默认 deepseek-chat |
| `OPENROUTER_API_KEY` | OpenRouter Key（sk-or-开头） | Gateway（GPT-4o/Claude/Gemini） |
| `SILICONFLOW_API_KEY` | 硅基流动 Key | Gateway（Embedding + Rerank） |
| `YUQUE_TOKEN` | 语雀 API Token | Gateway（日记同步） |
| `PROXY_URL` | HTTP代理地址 | Gateway（外部API请求） |
| `SERVERCHAN_KEY` | Server酱 Key | daily_diary.py（微信推送，可选） |
| `GATEWAY_PORT` | Gateway 端口 | Gateway，默认 8001 |
| `MEMU_PORT` | MemU 端口 | Gateway，默认 8000 |
| `MEMU_URL` | MemU 地址 | Gateway，默认 http://localhost:8000 |

**Gateway config.py 加载方式**：pydantic_settings `BaseSettings`，env_file 指向 `/home/dream/memory-system/.env`
**晨的助手加载方式**：`python-dotenv` 的 `load_dotenv("/home/dream/memory-system/.env")` + `os.getenv()`
**diary_api.py 加载方式**：`load_dotenv()` 从当前目录 .env 读取

---

## 十二、版本历史

| 版本 | 时间 | 主要变更 |
|------|----------|----------|
| 初始 | 2026-01-22 | 搭建 Kelivo Gateway 基础代理 + Supabase 对话存储 |
| v1.x | 2026-01-24 ~ 01-26 | 添加 ChromaDB 本地向量搜索、MemU 集成、语雀同步 |
| v2.0 | 2026-01-31 | mcp_server.py 独立 MCP 服务器（晨的助手前身） |
| v5.0 | 2026-02-03 | 晨的助手升级：3个工具（query/save/delete）、4种数据类型（expense/memory/chat_memory/diary） |
| v7.0 | 2026-02-04 | 晨的助手重构：统一工具模式，精简代码 |
| **v8.0** | **2026-02-18** | **晨的助手**：4个工具（+update）、7种数据类型（+promise/wishlist/milestone）|
| | | **Gateway v2.2**：场景检测 + 混合检索 + 自动注入 + pgvector + 同义词服务 |
| | | **数据库**：conversations/summaries 新增 scene_type/topic/entities/emotion/embedding 字段 |
| | | **数据库**：新增 synonym_map 表 + RPC搜索函数 |
| | | **向量迁移**：ChromaDB → Supabase pgvector（删除 embedding_service.py + chroma_db/） |
| | | **网站v2**：新增 memories/milestones/promises/wishlists 页面 |
| | | **diary_api v2**：新增 milestones/promises/wishlists/chat_memories 只读API |
| | | **模型扩展**：新增 Antigravity 通道、GCLI2API 本地 Gemini、假流式处理 |
| | | **安全修复**：claude_assistant_api.py 硬编码凭据改为从 .env 读取 |
| | | **项目肃清**：删除8个废弃文件 + chroma_db 目录 |

---

## 十三、待办清单

### P0 — 紧急（需在服务器上手动执行）

- [ ] `crontab -e` 注释掉凌晨3点的 cleanup_cron.py 行（脚本已删除）
- [ ] 重启8002服务（claude_assistant_api.py 已修改凭据读取方式）

### P1 — 高优先级

- [ ] 排查阿里云 CPU 偶尔飙升95%问题（可能与后台同步服务有关）
- [ ] conversations 表建 ivfflat 向量索引（需表中有一定数据量后执行）
  ```sql
  CREATE INDEX idx_conv_embedding ON conversations
  USING ivfflat(embedding vector_cosine_ops) WITH (lists = 50);
  ```

### P2 — 中优先级

- [ ] 日记页面加密码保护（目前无需登录即可查看）
- [ ] Claude模型在Gateway中空回复问题排查（OpenRouter的Claude模型名格式）
- [ ] 语雀+外置记忆库更新迭代

### P3 — 低优先级

- [ ] 网站扩展：文字板块、恋爱历程等内容
- [ ] CLAUDE.md 中的文件结构和功能描述需同步更新（部分内容已过时）
- [ ] 考虑给 synonym_map 做一个管理界面（目前只能通过SQL管理）

---

## 十四、安全规则速查

**绝对禁止**：
1. 不要在代码中硬编码密钥/Token/API Key
2. 不要在git commit中包含.env内容
3. 不要kill正在运行的8001/8002/8003进程（除非Dream同意）
4. 不要直接修改宝塔管理的Nginx配置
5. 不要修改crontab中的现有条目

**修改前必须备份**：
```bash
cp 文件名 文件名.bak.$(date +%Y%m%d%H%M%S)
```

**可以自由操作**：website/目录、diary_api.py、nginx/参考配置、新建文件、Git操作

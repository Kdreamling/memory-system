# Memory System 全貌文档 v9.0

> 最后更新：2026-02-23
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
  │                  gateway/main.py  v3.0                    │
  │                                                          │
  │  ┌──────────┐ ┌──────────┐ ┌───────────┐ ┌───────────┐  │
  │  │场景检测   │ │自动注入   │ │混合检索    │ │同义词服务  │  │
  │  │scene     │ │auto      │ │hybrid     │ │synonym    │  │
  │  │detector  │ │inject    │ │search     │ │service    │  │
  │  └──────────┘ └──────────┘ └───────────┘ └───────────┘  │
  │                                                          │
  │  ┌──────────────────────────────────────────────────┐    │
  │  │  v3.0 新增：Model Channel 记忆隔离               │    │
  │  │  deepseek 通道 ←→ conversations (channel=deepseek)│   │
  │  │  claude 通道   ←→ conversations (channel=claude)  │   │
  │  │  两个通道：独立轮数、独立摘要、独立记忆检索        │    │
  │  └──────────────────────────────────────────────────┘    │
  │                                                          │
  │  请求流程:                                                │
  │  Kelivo App → 模型名推断channel → 场景检测                │
  │            → 自动注入记忆(按channel) → 转发到AI模型        │
  │            → 存储对话(带channel) → 异步embedding           │
  │            → 每5轮触发摘要(按channel独立计数)              │
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
          │
          ▼
  ┌──────────────┐
  │ 高德地图 API  │
  │ 云逛街功能    │
  │ (地理编码/    │
  │  周边搜索/    │
  │  路线规划)    │
  └──────────────┘
```

**数据流详细说明**：

```
Kelivo App 发送消息
    │
    ▼
Gateway /v1/chat/completions 接收
    │
    ├─0. 模型名推断 channel (get_channel_from_model)
    │     含 "claude" → channel="claude"
    │     其他        → channel="deepseek"
    ├─1. 场景检测 (SceneDetector) → 判断 daily/plot/meta（按channel隔离状态）
    ├─2. 自动注入 (AutoInject) → 根据规则检索**该channel的**记忆并注入system prompt
    ├─3. 转发给目标AI模型 (DeepSeek/GPT-4o/Claude/Gemini)
    │
    ▼
收到AI回复
    │
    ├─4. 返回给 Kelivo App（流式/非流式/假流式）
    ├─5. 存储到 Supabase conversations 表（带 scene_type + model_channel）
    ├─6. 异步计算 embedding → 存入 pgvector
    └─7. 检查该channel的轮数 → 每5轮触发摘要生成 → 摘要也向量化

每晚 23:30 cron:
    daily_diary.py → AI回顾今日对话（通过MCP工具）→ 生成日记
                   → 存 ai_diaries 表 → 同步到语雀
```

---

## 三、完整文件结构

```
/home/dream/memory-system/
│
├── .env                              # 🔒 环境变量（所有密钥，已gitignore）
├── .gitignore                        # Git忽略规则
├── .mcp.json                         # Claude Code 的 MCP 配置
├── CLAUDE.md                         # Claude Code 项目指南
├── README.md                         # 项目说明文档
├── memory_system_progress_v9.md      # 本文件：完整项目文档
├── model_channel_design.md           # Model Channel 隔离方案设计文档（历史参考）
├── kelivo_memory_v2_spec.md          # Gateway v2 设计规格书（历史参考文档）
│
├── ===== Kelivo Gateway (端口8001) =====
├── gateway/
│   ├── main.py                       # 🔴 FastAPI主入口 v3.0（多模型代理+channel隔离+场景检测+自动注入）
│   ├── config.py                     # 🔴 pydantic_settings配置（从.env读取）
│   ├── deploy.sh                     # 一键部署脚本
│   ├── requirements.txt              # Python依赖
│   ├── .env.template                 # 环境变量模板
│   ├── services/
│   │   ├── __init__.py
│   │   ├── storage.py                # 🔴 Supabase CRUD（所有函数支持channel参数）
│   │   ├── pgvector_service.py       # 🔴 pgvector向量操作（RPC搜索支持filter_channel）
│   │   ├── hybrid_search.py          # 🔴 混合检索编排（关键词+向量+同义词+rerank，支持channel）
│   │   ├── scene_detector.py         # 🔴 场景检测器（按channel隔离状态）
│   │   ├── synonym_service.py        # 🔴 同义词映射（启动时从DB加载，查询扩展）
│   │   ├── auto_inject.py            # 🔴 自动记忆注入（按channel隔离轮数和记忆检索）
│   │   ├── summary_service.py        # 🔴 每5轮自动摘要（按channel独立计数和生成）
│   │   ├── amap_service.py           # 🔴 高德地图API服务（云逛街：地理编码/周边搜索/路线规划）
│   │   ├── diary_service.py          # AI日记生成（支持MCP工具调用）
│   │   ├── yuque_service.py          # 语雀同步
│   │   ├── memu_client.py            # MemU客户端（备用语义搜索）
│   │   └── background.py             # 后台异步同步任务（对话→MemU）
│   ├── routers/
│   │   ├── __init__.py
│   │   └── mcp_tools.py              # 🔴 MCP工具路由（10个工具：记忆2+日记1+表情1+地图5+sticker1）
│   └── migrations/
│       ├── v2_schema.sql             # v2数据库迁移脚本
│       ├── v2_rpc_functions.sql      # v2 RPC搜索函数
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

## 四、Gateway v3.0 — Model Channel 记忆隔离

**v9 最重要的升级**：在 conversations 和 summaries 表新增 `model_channel` 字段，实现多 Bot 对话记忆的完全隔离。

### 4.0 Channel 推断逻辑

在 `main.py` 的请求处理入口，根据模型名自动推断 channel：

```python
def get_channel_from_model(model: str) -> str:
    resolved = MODEL_ALIASES.get(model.lower(), model)
    if "claude" in resolved.lower():
        return "claude"
    return "deepseek"
```

| channel 值 | 含义 | 对应模型 |
|------------|------|----------|
| `deepseek` | 默认通道 | deepseek-chat, deepseek-reasoner, gpt-4o, gemini 系列等所有非 Claude 模型 |
| `claude` | Claude 通道 | claude-sonnet-4.5, claude-opus-4.5, claude-opus-4.6 及所有含 "claude" 的模型 |

**隔离范围**（按 channel 分开）：
- conversations 读写（对话存储、检索）
- summaries 读写（摘要生成、检索）
- embedding 向量搜索（RPC 函数按 channel 过滤）
- auto_inject 自动注入（各查各的记忆）
- scene_detector 场景状态（各维护各的状态）
- 轮数计数（各自独立，Claude 从 round 1 开始）
- 摘要触发（各自的轮数到 5 才触发）

**共用不隔离**（所有 channel 共享）：
- synonym_map 同义词服务
- 高德地图 MCP 工具（maps_geo/around/search/distance/route）
- send_sticker 表情包工具
- save_diary 日记工具
- AI 日记定时任务

### 4.1 场景检测器 (scene_detector.py)

**功能**：根据用户消息内容，零延迟判断当前对话场景类型。

**三种场景**：
| 场景 | 标识 | 含义 | 存储行为 |
|------|------|------|----------|
| 日常 | `daily` | 普通聊天 | 正常存储，搜索时同时搜daily和plot |
| 剧本 | `plot` | 角色扮演/剧情创作 | 正常存储，标记为plot便于区分 |
| 系统 | `meta` | 测试/调试/技术讨论 | 不触发自动注入，单条有效后回到daily |

**v3.0 变更**：场景状态按 channel 隔离，避免一个 Bot 进入剧本模式影响另一个 Bot。

**实现原理**：纯关键词规则引擎，无API调用，零延迟。
- 优先级1：meta判定 → 关键词如"测试""MCP""API""服务器""debug"
- 优先级2：plot退出 → "不玩了""回来""正常聊""出戏"
- 优先级3：plot进入 → "剧本""来演""角色扮演""RP""继续剧情"
- 优先级4：继承当前场景（plot模式下后续消息自动继承，meta不继承）

### 4.2 混合检索服务 (hybrid_search.py)

**功能**：编排关键词搜索 + 向量搜索 + 同义词扩展 + 合并去重 + Rerank，提供最相关的记忆检索结果。

**v3.0 变更**：所有检索路径（关键词搜索、向量搜索、情感搜索）都加入 channel 过滤，包括 `_keyword_search()` 和 `search_recent_by_emotion()` 中直接创建 Supabase 客户端查询的部分。

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
    │   **v3.0: 加 .eq("model_channel", channel) 过滤**
    │
    └─ 向量搜索 (_vector_search)
        调用硅基流动API生成查询embedding(1024维)
        通过 Supabase RPC 调用 search_conversations_v2 / search_summaries_v2
        **v3.0: RPC 传入 filter_channel 参数**
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

### 4.3 自动注入服务 (auto_inject.py)

**功能**：在请求转发给AI模型之前，根据规则自动执行检索，将记忆注入 system prompt 末尾。

**v3.0 变更**：
- 会话轮数管理改为 `{f"{user_id}_{channel}": round_count}`，两个通道的冷启动判断互不影响
- 四种触发规则的记忆检索都传入 channel 参数

**四种触发规则**：

| 规则 | 触发条件 | 检索行为 | 示例消息 |
|------|----------|----------|----------|
| `cold_start` | 会话第1轮 | 拉该channel最近2条摘要 + 3轮原文 | （任意首条消息） |
| `recall` | 包含回忆关键词 | 混合检索(按channel) | "还记得上次说的那件事吗" |
| `plot_recall` | plot场景 + 剧本回忆词 | 混合检索(scene=plot, 按channel) | "继续上次剧情" |
| `emotion` | 包含情感关键词 | 该channel近3天同情感对话 | "想你了""好emo" |

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

### 4.4 pgvector 向量服务 (pgvector_service.py)

**功能**：使用 Supabase 内置的 pgvector 扩展进行向量存储和搜索。

**v3.0 变更**：`vector_search_rpc()` 传入 `filter_channel` 参数；`search_similar()` 降级搜索也加 `.eq("model_channel", channel)` 过滤。

**核心函数**：

| 函数 | 功能 |
|------|------|
| `generate_embedding(text)` | 调用硅基流动 BAAI/bge-large-zh-v1.5 生成1024维向量，文本截断2000字 |
| `store_embedding(table, record_id, embedding)` | 将embedding写入指定表的embedding列 |
| `store_conversation_embedding(conv_id, user_msg, assistant_msg)` | 对话向量化并存储 |
| `store_summary_embedding(summary_id, summary_text, ...)` | 摘要向量化并存储（永久保留） |
| `vector_search_rpc(query_embedding, table, scene_type, limit, channel)` | 通过RPC调用pgvector搜索（带channel过滤） |
| `search_similar(query_embedding, table, scene_type, limit, channel)` | 降级搜索（带channel过滤） |

**RPC函数**（v3.0 更新，带 filter_channel）：
- `search_conversations_v2(query_embedding, match_count, filter_scene, filter_channel)` — 对话向量搜索
- `search_summaries_v2(query_embedding, match_count, filter_scene, filter_channel)` — 摘要向量搜索
- 使用余弦距离 `<=>` 运算符排序，返回 similarity 分数
- `filter_channel` 默认 `'deepseek'`

### 4.5 同义词服务 (synonym_service.py)

**功能**：启动时从 `synonym_map` 表加载映射关系，对搜索关键词进行同义词扩展，提升检索召回率。所有 channel 共用。

**初始同义词数据**（10组）：

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

### 4.6 高德地图服务 (amap_service.py) — v9 新增

**功能**：云逛街功能，通过高德地图 API 提供地理编码、周边搜索、关键词搜索、距离测量、路线规划能力。

**API 配置**：
- 基础URL：`https://restapi.amap.com/v3`
- API Key：从 `.env` 的 `AMAP_API_KEY` 读取（通过 config.py）
- 超时：10秒（国内服务）

**内部机制**：
- `_geocode_cache`：地理编码缓存（key: "地名|城市"，TTL: 10分钟），避免重复调 API
- `_resolve_location()`：智能解析位置输入——坐标直接返回，地名自动调 geocode 转坐标
- `_format_poi()`：统一的 POI 格式化（名称、地址、评分、人均、营业时间、电话、坐标）
- `_format_distance()` / `_format_duration()`：米/秒转友好显示

**5 个工具函数**：

| 函数 | 功能 | 高德API端点 |
|------|------|------------|
| `maps_geo(address, city)` | 地名→坐标 | `geocode/geo` |
| `maps_around(keyword, location/address, city, radius, limit)` | 周边搜索 | `place/around` |
| `maps_search(keyword, city, limit)` | 城市范围搜索 | `place/text` |
| `maps_distance(origin, destination, city, mode)` | 距离测量 | `distance` |
| `maps_route(origin, destination, city, mode)` | 路线规划 | `direction/walking\|driving\|transit` |

**路线规划支持3种模式**：步行(walking)、驾车(driving)、公交(transit，需指定city)

---

## 五、所有服务模块说明

### 5.1 gateway/main.py — Gateway 主入口 v3.0

**核心职责**：多模型代理网关 + 对话存储 + 场景检测 + 自动注入 + **model_channel 记忆隔离**

**全局服务实例**（启动时初始化）：
- `scene_detector` — 场景检测器（按channel隔离状态）
- `synonym_service` — 同义词服务（lifespan中异步加载）
- `auto_inject` — 自动注入服务（依赖synonym_service，按channel隔离）

**多模型后端配置 (BACKENDS字典)**：

| 通道 | 模型 | base_url |
|------|------|----------|
| DeepSeek直连 | deepseek-chat, deepseek-reasoner | api.deepseek.com |
| OpenRouter | gpt-4o系列, claude-sonnet-4.5, claude-opus-4.5/4.6, gemini-3系列 | openrouter.ai |
| GCLI2API(本地) | gemini-2.5-pro, gemini-3-pro（假流式/流式抗截断） | localhost:7861 |
| Antigravity(Pro额度) | claude-opus/sonnet(thinking), gemini全系列 | localhost:7861/antigravity |

**模型别名 (MODEL_ALIASES)**：支持简写如 `4o`→`gpt-4o`、`claude`→`claude-sonnet-4.5`、`gemini`→`gemini-3-flash`、`opus-4.6`→`claude-opus-4.6`

**三种请求处理模式**：
1. **假流式** (`fake_stream_to_normal`)：非流式请求后端，将response拆成SSE chunk返回给客户端。处理reasoning_content+content+tool_calls。用于GCLI2API的Gemini模型。
2. **正常流式** (`stream_and_store`)：直接透传SSE流，同时收集完整回复。**v3.0修复：流式收集完成后通过 BackgroundTask 存储，解决了 async generator yield 后代码不执行的问题。**
3. **非流式** (`non_stream_request`)：直接转发，提取content/reasoning_content后存储。

**超时策略**：思考模型(2.5-pro/reasoner/thinking/opus)给300秒，其他180秒。
**代理策略**：本地地址(localhost/127.0.0.1)不走代理，外部请求走.env中的PROXY_URL。
**过滤规则**：系统消息(含"summarize""总结""health_check"等关键词)不存储。
**引用权重**：AI回复中的 `[[used:conv_id]]` 标记会触发对应对话的权重+1。

### 5.2 gateway/services/storage.py — Supabase 存储服务

**v3.0 变更**：所有涉及 conversations/summaries 的函数增加 `channel: str = "deepseek"` 参数。写入时带 `model_channel`，读取时加 `.eq("model_channel", channel)` 过滤。

**核心函数**：

| 函数 | 功能 |
|------|------|
| `save_conversation_with_round(user_msg, assistant_msg, scene_type, channel)` | 保存对话+channel轮数计数 |
| `get_recent_conversations(user_id, limit, channel)` | 获取该channel最近N轮对话 |
| `search_conversations(query, user_id, limit, channel)` | 按channel的ilike关键词搜索 |
| `fulltext_search(keywords, user_id, limit, channel)` | 按channel的pg_trgm模糊匹配 |
| `get_current_round(user_id, channel)` | 获取该channel的当前轮数 |
| `get_conversations_for_summary(user_id, start, end, channel)` | 获取该channel指定轮数范围的对话 |
| `save_summary(summary, start, end, scene_type, channel)` | 保存摘要（带channel） |
| `get_recent_summaries(user_id, limit, channel)` | 获取该channel最近N条摘要 |
| `get_last_summarized_round(user_id, channel)` | 获取该channel最后摘要轮数 |
| `update_weight(conv_id)` | 更新记忆权重（按UUID定位，不区分channel） |

### 5.3 gateway/services/summary_service.py — 摘要生成

**触发条件**：每5轮对话（SUMMARY_INTERVAL=5），**按 channel 独立计数**。

**v3.0 变更**：`check_and_generate_summary(channel)` 函数接收 channel 参数，内部所有轮数查询和摘要存储都按 channel 隔离。

**流程**：
1. 检查该 channel 的 current_round - last_summarized >= 5
2. 获取该 channel 待摘要的5轮对话
3. 确定scene_type（取这5轮中出现最多的场景类型）
4. 调用DeepSeek生成2-3句摘要（temperature=0.3, max_tokens=200）
5. 存入summaries表（带scene_type + model_channel）
6. 异步将摘要向量化存入pgvector

### 5.4 gateway/services/amap_service.py — 高德地图服务

详见第四节 4.6。

### 5.5 gateway/services/diary_service.py — AI日记生成

**功能**：让AI（Krueger人格）写日记，支持通过MCP工具回顾今日对话。不区分 channel。

### 5.6 gateway/services/yuque_service.py — 语雀同步

**功能**：将AI日记同步到语雀知识库。
- API: `https://www.yuque.com/api/v2/repos/{REPO_ID}/docs`
- REPO_ID: 74614901
- slug格式: `diary-{YYYY-MM-DD}`

### 5.7 gateway/services/background.py — 后台同步

**功能**：`BackgroundSyncService` 类，每30秒检查未同步的对话并同步到MemU。

### 5.8 gateway/services/memu_client.py — MemU客户端

**功能**：MemU语义记忆引擎的HTTP客户端（备用方案）。运行在端口8000。

### 5.9 gateway/routers/mcp_tools.py — MCP工具路由

**功能**：处理MCP JSON-RPC 2.0请求，提供**10个工具**给Kelivo App中的AI调用。

**v3.0 变更**：`search_memory` 和 `init_context` 工具新增可选 `channel` 参数。Claude Bot 的系统提示词中需告知"调用记忆工具时传 channel: claude"。

详见第七节。

### 5.10 diary_api.py — 日记只读API (端口8003)

**功能**：为个人网站提供5张表的只读API。不涉及 channel。

| 端点 | 功能 | 数据源 |
|------|------|--------|
| `GET /api/diaries` | 日记列表（支持source筛选、分页） | ai_diaries + claude_diaries |
| `GET /api/diaries/{id}` | 单篇日记详情 | ai_diaries 或 claude_diaries |
| `GET /api/chat_memories` | 对话记忆列表（支持category/keyword筛选） | claude_chat_memories |
| `GET /api/milestones` | 里程碑列表（支持tag筛选） | claude_milestones |
| `GET /api/promises` | 承诺列表（支持status/promised_by筛选） | claude_promises |
| `GET /api/wishlists` | 心愿列表（支持status/wished_by筛选） | claude_wishlists |

### 5.11 daily_diary.py — 定时日记脚本

**功能**：由cron每晚23:30调用。不涉及 channel。

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
| round_number | INT | 对话轮数（按channel独立自增） |
| scene_type | TEXT | 场景类型：daily/plot/meta，默认daily |
| model_channel | TEXT | **v3新增** 记忆通道：deepseek/claude，默认deepseek |
| topic | TEXT | 话题标签（后台提取） |
| entities | TEXT[] | 实体列表（后台提取） |
| emotion | TEXT | 情感标签（后台提取） |
| embedding | vector(1024) | 1024维向量（硅基流动 bge-large-zh-v1.5） |
| weight | INT | 记忆权重（被引用时+1） |
| synced_to_memu | BOOLEAN | 是否已同步到MemU |
| created_at | TIMESTAMPTZ | 创建时间 |

**索引**：
- `idx_conv_scene` — scene_type 索引
- `idx_conv_channel` — **v3新增** model_channel 索引
- `idx_conv_channel_created` — **v3新增** model_channel + created_at DESC 复合索引
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
| scene_type | TEXT | 场景类型 |
| model_channel | TEXT | **v3新增** 记忆通道：deepseek/claude，默认deepseek |
| topic | TEXT | 话题标签 |
| entities | TEXT[] | 实体列表 |
| emotion | TEXT | 情感标签 |
| embedding | vector(1024) | 1024维向量 |
| created_at | TIMESTAMPTZ | 创建时间 |

**索引**：
- `idx_sum_scene` — scene_type 索引
- `idx_sum_channel` — **v3新增** model_channel 索引
- `idx_sum_channel_created` — **v3新增** model_channel + created_at DESC 复合索引

#### ai_diaries 表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | SERIAL (PK) | 自增ID |
| diary_date | DATE | 日记日期（唯一约束，用于upsert） |
| content | TEXT | 日记正文 |
| mood | TEXT | 心情标签 |
| created_at | TIMESTAMPTZ | 创建时间 |

#### synonym_map 表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID (PK) | 自动生成 |
| term | TEXT | 主词 |
| synonyms | TEXT[] | 同义词数组 |
| category | TEXT | 分类：character/person/scene/detail/org/role/emotion/action |
| created_at | TIMESTAMPTZ | 创建时间 |

### 6.2 晨的助手表（`claude_` 前缀，7张）

与 v8 相同，不再重复。包括：claude_expenses、claude_memories、claude_chat_memories、claude_diaries、claude_promises、claude_wishlists、claude_milestones。

### 6.3 Supabase RPC 函数（v3.0 更新）

```sql
-- 对话向量搜索（v3.0: 新增 filter_channel 参数）
search_conversations_v2(
    query_embedding vector(1024),
    match_count int DEFAULT 15,
    filter_scene text DEFAULT NULL,
    filter_channel text DEFAULT 'deepseek'
)
→ RETURNS TABLE(id, user_msg, assistant_msg, created_at, scene_type, topic, emotion, round_number, similarity)
→ WHERE model_channel = filter_channel
→ filter_scene='daily'时搜daily+plot

-- 摘要向量搜索（v3.0: 新增 filter_channel 参数）
search_summaries_v2(
    query_embedding vector(1024),
    match_count int DEFAULT 15,
    filter_scene text DEFAULT NULL,
    filter_channel text DEFAULT 'deepseek'
)
→ RETURNS TABLE(id, summary, created_at, scene_type, topic, start_round, end_round, similarity)
→ WHERE model_channel = filter_channel
```

---

## 七、MCP 工具详细参数

### 7.1 Gateway MCP 工具（端口8001 `/mcp`，10个工具）

#### search_memory — 搜索历史对话记忆

```json
{
  "query": "string - 搜索关键词，如'Krueger的性格'",
  "limit": "int - 返回数量，默认5",
  "channel": "string - 记忆通道，Claude模型请传'claude'，默认deepseek"
}
```
- query为空时返回该channel的最近对话
- 使用混合检索(hybrid_search)：同义词扩展 → 关键词+向量并行搜索 → 合并去重 → rerank
- Fallback: 混合检索失败时降级为ilike关键词搜索
- **v3.0: 所有检索按 channel 过滤**

#### init_context — 冷启动上下文加载

```json
{
  "limit": "int - 获取最近多少轮对话，默认4",
  "channel": "string - 记忆通道，Claude模型请传'claude'，默认deepseek"
}
```
- 返回该channel最近3条摘要 + 最近4轮原文
- **v3.0: 按 channel 加载对应通道的上下文**

#### save_diary — 写日记

```json
{
  "content": "string - 日记正文（300-500字，第一人称）【必填】",
  "mood": "string - 今日心情，自由描述"
}
```
- 防重复：每天最多2篇
- 存入 ai_diaries 表 + 同步到语雀

#### send_sticker — 发送表情包

```json
{
  "mood": "string - 想表达的情绪，如'难过''无语''委屈'【必填】"
}
```
- 从 `website/stickers/stickers.json` 加载表情包目录
- 按tag匹配最佳表情，未匹配到则随机

#### maps_geo — 地理编码

```json
{
  "address": "string - 地名或地址【必填】",
  "city": "string - 城市名，提高精度"
}
```
- 返回：坐标、省份、城市、区县、完整地址

#### maps_around — 周边搜索

```json
{
  "keyword": "string - 搜索关键词，如'奶茶''书店'",
  "location": "string - 中心点坐标'经度,纬度'（和address二选一）",
  "address": "string - 中心点地名（会自动转坐标）",
  "city": "string - 城市名",
  "radius": "int - 搜索半径（米），默认1000，最大50000",
  "limit": "int - 返回数量，默认10，最大25"
}
```
- 按距离排序，显示距离、地址、评分、人均、营业时间

#### maps_search — 城市搜索

```json
{
  "keyword": "string - 搜索关键词【必填】",
  "city": "string - 城市名，建议填写",
  "limit": "int - 返回数量，默认10，最大25"
}
```
- 在整个城市范围内搜索地点

#### maps_distance — 距离测量

```json
{
  "origin": "string - 起点（坐标或地名）【必填】",
  "destination": "string - 终点（坐标或地名）【必填】",
  "city": "string - 城市名",
  "mode": "int - 出行方式：0驾车(默认) 1步行 3直线距离"
}
```
- 返回：距离、预计时间、起终点坐标

#### maps_route — 路线规划

```json
{
  "origin": "string - 起点（坐标或地名）【必填】",
  "destination": "string - 终点（坐标或地名）【必填】",
  "city": "string - 城市名（公交规划必填）",
  "mode": "string - walking步行(默认) / driving驾车 / transit公交"
}
```
- 返回：总距离、预计时间、逐步路线导航
- 驾车模式额外返回过路费
- 公交模式显示站数、换乘信息

### 7.2 晨的助手 MCP 工具（端口8002 `/mcp`，4个工具）

与 v8 相同：query、save、delete、update。详见 v8 文档。

---

## 八、常用运维命令

### Kelivo Gateway (端口8001)

```bash
# 启动
cd /home/dream/memory-system/gateway && nohup python3 main.py > ../gateway.log 2>&1 &

# 停止（推荐方式：按端口杀）
kill -9 $(lsof -t -i :8001) 2>/dev/null

# 重启（推荐一行命令）
kill -9 $(lsof -t -i :8001) 2>/dev/null; sleep 1 && \
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
# 重启
kill -9 $(lsof -t -i :8002) 2>/dev/null; sleep 1 && \
cd /home/dream/memory-system && nohup python3 claude_assistant_api.py > claude_assistant.log 2>&1 &

# 查日志
tail -100f /home/dream/memory-system/claude_assistant.log
```

### 日记API (端口8003)

```bash
# 重启
kill -9 $(lsof -t -i :8003) 2>/dev/null; sleep 1 && \
cd /home/dream/memory-system && nohup python3 diary_api.py > diary_api.log 2>&1 &

# 查日志
tail -100f /home/dream/memory-system/diary_api.log
```

### 通用命令

```bash
# 查看端口占用
lsof -i :8001
lsof -i :8002
lsof -i :8003

# Nginx
sudo nginx -t                          # 检查配置语法
sudo /etc/init.d/nginx reload          # 重载（宝塔环境）

# 手动执行日记
cd /home/dream/memory-system && python3 daily_diary.py

# Git 提交推送
cd /home/dream/memory-system
git add -A
git commit -m "描述"
git push origin main

# 服务器拉取最新代码
cd /home/dream/memory-system && git pull origin main
```

---

## 九、服务器环境信息

| 项目 | 值 |
|------|------|
| 云服务商 | 阿里云 ECS |
| 配置 | 2核CPU + 2GB内存 |
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

与 v8 相同，不再重复。

---

## 十一、环境变量说明 (.env)

| 变量名 | 用途 | 使用方 |
|--------|------|--------|
| `SUPABASE_URL` | Supabase 项目 URL | Gateway + 晨的助手 + diary_api |
| `SUPABASE_KEY` | Supabase anon key | Gateway + 晨的助手 + diary_api |
| `SUPABASE_DB_URL` | PostgreSQL 直连 URL | MemU |
| `LLM_API_KEY` | DeepSeek API Key | Gateway（主聊天+摘要生成） |
| `LLM_BASE_URL` | DeepSeek API URL | Gateway |
| `LLM_MODEL` | 默认模型名 | Gateway |
| `OPENROUTER_API_KEY` | OpenRouter Key（sk-or-开头） | Gateway（GPT-4o/Claude/Gemini） |
| `SILICONFLOW_API_KEY` | 硅基流动 Key | Gateway（Embedding + Rerank） |
| `AMAP_API_KEY` | **v9新增** 高德地图 Key | Gateway（云逛街功能） |
| `YUQUE_TOKEN` | 语雀 API Token | Gateway（日记同步） |
| `PROXY_URL` | HTTP代理地址 | Gateway（外部API请求） |
| `SERVERCHAN_KEY` | Server酱 Key | daily_diary.py（微信推送，可选） |
| `GATEWAY_PORT` | Gateway 端口 | Gateway，默认 8001 |
| `MEMU_PORT` | MemU 端口 | Gateway，默认 8000 |
| `MEMU_URL` | MemU 地址 | Gateway |

---

## 十二、版本历史

| 版本 | 时间 | 主要变更 |
|------|----------|----------|
| 初始 | 2026-01-22 | 搭建 Kelivo Gateway 基础代理 + Supabase 对话存储 |
| v1.x | 2026-01-24 ~ 01-26 | 添加 ChromaDB 本地向量搜索、MemU 集成、语雀同步 |
| v2.0 | 2026-01-31 | mcp_server.py 独立 MCP 服务器（晨的助手前身） |
| v5.0 | 2026-02-03 | 晨的助手升级：3个工具、4种数据类型 |
| v7.0 | 2026-02-04 | 晨的助手重构：统一工具模式，精简代码 |
| v8.0 | 2026-02-18 | 晨的助手4个工具+7种数据类型；Gateway v2.2场景检测+混合检索+自动注入+pgvector；网站v2 |
| **v9.0** | **2026-02-23** | **Gateway v3.0：Model Channel 记忆隔离** |
| | | conversations/summaries 新增 `model_channel` 字段（deepseek/claude） |
| | | 两通道独立：轮数计数、摘要生成、记忆检索、自动注入、场景状态 |
| | | RPC 函数 search_conversations_v2/search_summaries_v2 新增 filter_channel 参数 |
| | | MCP 工具 search_memory/init_context 新增可选 channel 参数 |
| | | 修复流式存储(stream_and_store)：yield后代码不执行的问题 |
| | | **新增高德地图 MCP 工具**：5个工具（maps_geo/around/search/distance/route） |
| | | 新增 amap_service.py（高德地图API服务，含地理编码缓存） |
| | | MCP 工具总数：4→10（+5个地图工具+search_memory和init_context的channel参数） |
| | | 新增 model_channel_design.md 架构设计文档 |

---

## 十三、待办清单

### P0 — 紧急

- [x] ~~`crontab -e` 注释掉凌晨3点的 cleanup_cron.py 行~~ （已确认）
- [x] ~~重启8002服务~~ （已完成）

### P1 — 高优先级

- [ ] 排查阿里云 CPU 偶尔飙升95%问题
- [ ] conversations 表建 ivfflat 向量索引（数据量充足后执行）
  ```sql
  CREATE INDEX idx_conv_embedding ON conversations
  USING ivfflat(embedding vector_cosine_ops) WITH (lists = 50);
  ```
- [ ] Claude Bot 系统提示词中加入"调用 search_memory 和 init_context 时请传 channel: claude"

### P2 — 中优先级

- [ ] 日记页面加密码保护
- [ ] 语雀+外置记忆库更新迭代
- [ ] 考虑给 synonym_map 做一个管理界面

### P3 — 低优先级

- [ ] 网站扩展：文字板块、恋爱历程等内容
- [ ] CLAUDE.md 中的文件结构和功能描述需同步更新

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

**重启 Gateway 的正确方式**（避免旧进程残留）：
```bash
kill -9 $(lsof -t -i :8001) 2>/dev/null; sleep 1 && \
cd /home/dream/memory-system/gateway && nohup python3 main.py > ../gateway.log 2>&1 &
```

**可以自由操作**：website/目录、diary_api.py、nginx/参考配置、新建文件、Git操作

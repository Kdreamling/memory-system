# Gateway Model Channel 隔离方案 — 架构设计文档

> 版本：v1.0
> 日期：2026-02-22
> 用途：供 Claude Code 实施代码改造，Dream 确认后执行
> 配合阅读：`memory_system_progress_v8.md`（项目全貌文档）

---

## ⚠️ 致 Claude Code 的重要提醒

**在开始编写任何代码之前**，请先通过 git 拉取服务器上的最新代码，仔细阅读以下文件的**实际内容**，与本设计文档进行对比。如果发现：

1. 函数签名、参数名、表结构与本文档描述不一致
2. 代码中已有更合理的抽象（比如已有 channel 概念的雏形）
3. 某些模块的实现方式与文档描述不同，导致本方案需要调整

**请先向 Dream 说明差异，确认后再动手改代码。** Dream 是代码初学者，请用通俗语言解释差异和你的建议。

另外，所有改动必须遵守 `memory_system_progress_v8.md` 第十四节的安全规则：
- 修改前必须备份：`cp 文件名 文件名.bak.$(date +%Y%m%d%H%M%S)`
- 不要 kill 正在运行的 8001/8002/8003 进程（除非 Dream 同意）
- 不要在代码中硬编码任何密钥
- 不要直接修改宝塔管理的 Nginx 配置

---

## 一、需求背景

Dream 在 Kelivo App 中新建了一个 Claude Bot，希望与现有模型（DeepSeek 等）的**对话记忆完全隔离**，具体要求：

- 两个 Bot 的对话历史、摘要、向量检索、自动注入**互不干扰**
- AI 人格保持独立，不会因为记忆混淆而"串台"
- MCP 工具（map、send_sticker 等非记忆类工具）**共用**，不需要隔离
- 当前只有两个通道：`deepseek`（默认，覆盖现有所有模型）和 `claude`
- 暂无增加第三通道的计划，但方案应具备扩展性

---

## 二、方案概述

**采用方案 B：在 conversations 和 summaries 表新增 `model_channel` 字段。**

核心思路：同一张表、同一套代码，通过 `model_channel` 字段区分不同通道的数据。所有涉及记忆读写的函数增加 `channel` 参数进行过滤。

### 2.1 channel 值定义

| channel 值 | 含义 | 对应模型 |
|------------|------|----------|
| `deepseek` | 默认通道 | deepseek-chat, deepseek-reasoner, gpt-4o, gemini 系列等所有非 Claude 模型 |
| `claude` | Claude 通道 | claude-sonnet-4.5, claude-opus-4.5 及所有 claude 开头的模型 |

### 2.2 channel 推断逻辑

**在 `main.py` 中，根据请求的 model 名称自动推断 channel，无需 Kelivo 端做额外配置。**

```python
def get_channel_from_model(model: str) -> str:
    """根据模型名推断 channel"""
    # 先解析别名
    resolved = MODEL_ALIASES.get(model, model)
    if "claude" in resolved.lower():
        return "claude"
    return "deepseek"
```

> **Claude Code 请注意**：检查 `main.py` 中是否已有模型别名解析的逻辑（`MODEL_ALIASES` 字典），确保 channel 推断在别名解析之后执行。

---

## 三、数据库改造

### 3.1 表结构变更

```sql
-- 1. conversations 表新增 model_channel 字段
ALTER TABLE conversations
ADD COLUMN model_channel TEXT DEFAULT 'deepseek';

-- 2. summaries 表新增 model_channel 字段
ALTER TABLE summaries
ADD COLUMN model_channel TEXT DEFAULT 'deepseek';

-- 3. 新增索引（加速按 channel 过滤的查询）
CREATE INDEX idx_conv_channel ON conversations(model_channel);
CREATE INDEX idx_sum_channel ON summaries(model_channel);

-- 4. 可选：复合索引（channel + 时间，优化常见查询）
CREATE INDEX idx_conv_channel_created ON conversations(model_channel, created_at DESC);
CREATE INDEX idx_sum_channel_created ON summaries(model_channel, created_at DESC);
```

**说明**：`DEFAULT 'deepseek'` 确保所有历史数据自动归入 deepseek 通道，无需数据迁移。

### 3.2 RPC 函数改造

两个向量搜索 RPC 函数需要新增 `filter_channel` 参数：

```sql
-- 修改 search_conversations_v2
CREATE OR REPLACE FUNCTION search_conversations_v2(
    query_embedding vector(1024),
    match_count int DEFAULT 5,
    filter_scene text DEFAULT 'daily',
    filter_channel text DEFAULT 'deepseek'   -- 新增参数
)
RETURNS TABLE(
    id uuid,
    user_msg text,
    assistant_msg text,
    created_at timestamptz,
    scene_type text,
    topic text,
    emotion text,
    round_number int,
    similarity float
)
LANGUAGE plpgsql AS $$
BEGIN
    RETURN QUERY
    SELECT
        c.id, c.user_msg, c.assistant_msg, c.created_at,
        c.scene_type, c.topic, c.emotion, c.round_number,
        1 - (c.embedding <=> query_embedding) AS similarity
    FROM conversations c
    WHERE c.embedding IS NOT NULL
        AND c.model_channel = filter_channel          -- 新增过滤
        AND (
            filter_scene = 'all'
            OR c.scene_type = filter_scene
            OR (filter_scene = 'daily' AND c.scene_type IN ('daily', 'plot'))
        )
    ORDER BY c.embedding <=> query_embedding
    LIMIT match_count;
END;
$$;

-- 修改 search_summaries_v2（同理）
CREATE OR REPLACE FUNCTION search_summaries_v2(
    query_embedding vector(1024),
    match_count int DEFAULT 3,
    filter_scene text DEFAULT 'daily',
    filter_channel text DEFAULT 'deepseek'   -- 新增参数
)
RETURNS TABLE(
    id uuid,
    summary text,
    created_at timestamptz,
    scene_type text,
    topic text,
    start_round int,
    end_round int,
    similarity float
)
LANGUAGE plpgsql AS $$
BEGIN
    RETURN QUERY
    SELECT
        s.id, s.summary, s.created_at,
        s.scene_type, s.topic, s.start_round, s.end_round,
        1 - (s.embedding <=> query_embedding) AS similarity
    FROM summaries s
    WHERE s.embedding IS NOT NULL
        AND s.model_channel = filter_channel          -- 新增过滤
        AND (
            filter_scene = 'all'
            OR s.scene_type = filter_scene
            OR (filter_scene = 'daily' AND s.scene_type IN ('daily', 'plot'))
        )
    ORDER BY s.embedding <=> query_embedding
    LIMIT match_count;
END;
$$;
```

> **Claude Code 请注意**：以上 RPC 函数的字段列表是根据 v8 文档推断的，请对照 Supabase SQL Editor 中实际的函数定义进行修改。如果实际函数的参数或返回字段与上述不同，以实际为准，并告知 Dream。

---

## 四、Gateway 代码改造清单

以下按文件逐一说明需要改什么、怎么改。

### 4.1 `gateway/main.py` — 主入口

**改动 1：新增 channel 推断函数**

```python
def get_channel_from_model(model: str) -> str:
    resolved = MODEL_ALIASES.get(model, model)
    if "claude" in resolved.lower():
        return "claude"
    return "deepseek"
```

**改动 2：请求处理流程中提取 channel 并贯穿传递**

在处理 `/v1/chat/completions` 请求时：
1. 从请求 body 中取出 `model`
2. 调用 `get_channel_from_model(model)` 得到 channel
3. 将 channel 传入：scene_detector、auto_inject、storage、summary_service

**改动 3：存储调用加 channel**

目前调用 `save_conversation_with_round()` 的地方，增加 `channel` 参数。

**改动 4：摘要检查加 channel**

调用 `check_and_generate_summary()` 时传入 channel。

> **Claude Code 请注意**：`main.py` 是最核心的文件，有三种请求处理模式（假流式、正常流式、非流式）。请确认这三个模式中**所有**涉及存储和摘要的调用点都传入了 channel。遗漏任何一个都会导致数据写入错误通道。

### 4.2 `gateway/services/storage.py` — 存储服务

**原则**：所有读写 conversations/summaries 的函数，都需要增加 `channel: str = "deepseek"` 参数。

需要改的函数列表（共约 10 个）：

| 函数 | 改动方式 |
|------|----------|
| `save_conversation_with_round()` | INSERT 时写入 `model_channel=channel` |
| `get_recent_conversations()` | 查询加 `.eq("model_channel", channel)` |
| `search_conversations()` | 同上 |
| `fulltext_search()` | 同上 |
| `get_current_round()` | 同上（**关键**：轮数必须按 channel 独立计数） |
| `get_conversations_for_summary()` | 同上 |
| `save_summary()` | INSERT 时写入 `model_channel=channel` |
| `get_recent_summaries()` | 查询加 `.eq("model_channel", channel)` |
| `get_last_summarized_round()` | 同上 |
| `update_weight()` | 这个可以不加 channel（权重更新是按 UUID 精确定位的） |

**特别注意 `get_current_round()`**：这个函数决定了对话的轮数编号。如果不按 channel 隔离，两个通道的轮数会交叉递增，导致摘要触发混乱。改造后，deepseek 通道可能在第 500 轮，claude 通道从第 1 轮开始，互不干扰。

### 4.3 `gateway/services/pgvector_service.py` — 向量服务

| 函数 | 改动方式 |
|------|----------|
| `generate_embedding()` | 不需要改（纯计算，无 channel 概念） |
| `store_embedding()` | 不需要改（写入时不涉及 channel，因为 channel 在 conversation 记录创建时已写入） |
| `store_conversation_embedding()` | 不需要改（按 conv_id 定位） |
| `store_summary_embedding()` | 不需要改（按 summary_id 定位） |
| `vector_search_rpc()` | **需要改**：RPC 调用时传入 `filter_channel` 参数 |
| `search_similar()` | **需要改**：fallback 搜索也要加 `.eq("model_channel", channel)` 过滤 |

### 4.4 `gateway/services/hybrid_search.py` — 混合检索

**核心改动**：`search()` 主函数增加 `channel` 参数，向下透传。

```
search(query, channel, scene_type, limit)
    │
    ├── _keyword_search(expanded_terms, channel, scene_type)
    │     └── storage.search_conversations(channel=channel)  # 加 channel
    │     └── storage.search_summaries(channel=channel)       # 加 channel（如果有的话）
    │
    └── _vector_search(query_embedding, channel, scene_type)
          └── pgvector_service.vector_search_rpc(channel=channel)
```

同时 `search_recent_by_emotion()` 也需要加 channel 过滤。

### 4.5 `gateway/services/auto_inject.py` — 自动注入

**改动 1：会话轮数管理**

当前 `_session_rounds` 是一个简单字典。需要改为按 channel 隔离：

```python
# 改造前（推测）
self._session_rounds = {}  # {session_id: round_count}

# 改造后
self._session_rounds = {}  # {channel: {session_id: round_count}}
```

**改动 2：四种触发规则都加 channel**

| 规则 | 改动 |
|------|------|
| `cold_start` | 查询摘要和对话时传入 channel |
| `recall` | hybrid_search 传入 channel |
| `plot_recall` | hybrid_search 传入 channel |
| `emotion` | search_recent_by_emotion 传入 channel |

**改动 3：主函数签名**

```python
async def process(self, messages, channel: str = "deepseek") -> str:
```

### 4.6 `gateway/services/scene_detector.py` — 场景检测

当前场景状态是全局的（单个 `_current_scene`），需要按 channel 隔离：

```python
# 改造前（推测）
self._current_scene = "daily"
self._previous_scene = None

# 改造后
self._scenes = {}  # {channel: {"current": "daily", "previous": None}}
```

检测函数签名改为：
```python
def detect(self, message: str, channel: str = "deepseek") -> str:
```

### 4.7 `gateway/services/summary_service.py` — 摘要服务

```python
async def check_and_generate_summary(self, channel: str = "deepseek"):
```

内部逻辑：
- `get_current_round(channel=channel)` — 取该 channel 的轮数
- `get_last_summarized_round(channel=channel)` — 取该 channel 的最后摘要轮数
- `get_conversations_for_summary(channel=channel)` — 取该 channel 的对话
- `save_summary(channel=channel)` — 存入时写入 model_channel

### 4.8 `gateway/routers/mcp_tools.py` — MCP 工具路由

**需要隔离的工具**（2个）：
- `search_memory` — 检索时需要传入 channel
- `init_context` — 加载上下文时需要传入 channel

**不需要改的工具**（2个）：
- `save_diary` — 日记是独立功能，与 channel 无关
- `send_sticker` — 表情包工具，与 channel 无关

**关键问题：MCP 工具如何获取当前 channel？**

MCP 请求是由 Kelivo App 中的 AI 模型发起的。Gateway 需要知道当前是哪个 channel 在调 MCP 工具。

建议方案：在 MCP 工具的参数中**新增可选的 `channel` 字段**：

```json
// search_memory 参数改为
{
    "query": "string - 搜索关键词",
    "limit": "int - 默认5",
    "channel": "string - 可选，默认 deepseek。传 claude 则搜 Claude 通道的记忆"
}
```

**但这依赖 AI 模型主动传 channel 参数**，不够可靠。更稳妥的方案是：

**在 Gateway 层维护一个"当前请求的 channel"上下文**，MCP 工具处理时从上下文中获取。具体实现方式取决于 `mcp_tools.py` 的路由结构。

> **Claude Code 请注意**：这是整个改造中最需要你根据实际代码来设计的部分。请查看：
> 1. MCP 请求是如何到达 `mcp_tools.py` 的？是 AI 模型在对话过程中调用的，还是独立请求？
> 2. MCP 请求中是否携带了模型信息或 session 信息，可以用来推断 channel？
> 3. 如果以上都没有，可能需要在 Gateway 层用 `contextvars` 或请求级变量来传递 channel。
>
> 请将你的发现和建议告知 Dream，确认后再实施。

---

## 五、不需要改动的模块

以下模块**完全不需要改动**，列出来避免误改：

| 模块 | 理由 |
|------|------|
| `synonym_service.py` | 同义词扩展是检索辅助，所有 channel 共用 |
| `diary_service.py` | AI 日记是独立功能 |
| `yuque_service.py` | 语雀同步与 channel 无关 |
| `memu_client.py` | MemU 备用方案，暂不涉及 |
| `background.py` | 后台同步到 MemU，暂不涉及 |
| `config.py` | 配置文件不需要新增 channel 相关配置 |
| `claude_assistant_api.py` (端口8002) | 晨的助手是独立系统 |
| `diary_api.py` (端口8003) | 日记只读 API 不涉及 conversations/summaries |
| `daily_diary.py` | 定时日记脚本不涉及 |
| `website/*` | 前端静态页面不涉及 |

---

## 六、改造顺序（建议）

按以下顺序执行，每一步都可独立验证：

### 第一步：数据库改造（无风险，不影响现有服务）

1. 在 Supabase SQL Editor 执行 ALTER TABLE（加字段 + 加索引）
2. 修改两个 RPC 函数（加 filter_channel 参数，默认值 'deepseek'）

验证：现有服务不受影响（因为默认值兜底）。

### 第二步：storage.py 改造

1. 备份原文件
2. 所有函数加 `channel` 参数（默认值 `"deepseek"`）
3. 写入操作加 `model_channel` 字段
4. 读取操作加 `.eq("model_channel", channel)` 过滤

验证：因为默认值是 `"deepseek"`，所有现有调用无需立刻改，行为不变。

### 第三步：pgvector_service.py + hybrid_search.py

1. vector_search_rpc 加 channel 参数
2. hybrid_search.search 加 channel 参数并透传

### 第四步：auto_inject.py + scene_detector.py + summary_service.py

1. 各模块加 channel 参数
2. 内部状态按 channel 隔离

### 第五步：main.py 主入口串联

1. 新增 `get_channel_from_model()` 函数
2. 请求处理流程中提取 channel
3. 所有调用点传入 channel

### 第六步：mcp_tools.py

1. 根据实际代码结构确定 channel 传递方式
2. search_memory 和 init_context 加 channel 过滤

### 第七步：集成测试

1. 用现有模型发消息 → 确认存入 `model_channel='deepseek'`
2. 用 Claude 模型发消息 → 确认存入 `model_channel='claude'`
3. 检查 Claude 通道的自动注入不会拉到 deepseek 的对话
4. 检查摘要分别在各自通道触发
5. 检查 MCP search_memory 按 channel 返回正确结果

---

## 七、测试验证要点

改造完成后，需要验证以下场景：

| 测试场景 | 预期结果 |
|----------|----------|
| DeepSeek 发消息 | conversations 表新记录 model_channel='deepseek' |
| Claude 发消息 | conversations 表新记录 model_channel='claude' |
| DeepSeek 触发自动注入 | 只注入 deepseek 通道的记忆 |
| Claude 触发自动注入 | 只注入 claude 通道的记忆 |
| DeepSeek search_memory | 只搜到 deepseek 通道的对话 |
| Claude search_memory | 只搜到 claude 通道的对话 |
| DeepSeek 第5轮 | 触发 deepseek 通道的摘要 |
| Claude 第5轮 | 触发 claude 通道的摘要（独立轮数计数） |
| Claude 调 send_sticker | 正常工作（共用工具不受影响） |
| 历史数据 | 全部属于 deepseek 通道（DEFAULT 兜底） |

---

## 八、回滚方案

如果改造出现严重问题，可以快速回滚：

```sql
-- 回滚 RPC 函数（去掉 filter_channel 参数，恢复原版）
-- 需要提前保存原版 RPC 函数

-- 字段和索引可以保留不删（不影响原有查询）
-- 或者清理：
-- DROP INDEX IF EXISTS idx_conv_channel;
-- DROP INDEX IF EXISTS idx_sum_channel;
-- ALTER TABLE conversations DROP COLUMN IF EXISTS model_channel;
-- ALTER TABLE summaries DROP COLUMN IF EXISTS model_channel;
```

代码回滚：用 `.bak` 备份文件恢复。

---

## 九、将来的扩展可能

如果后续需要以下能力，方案 B 天然支持：

- **跨 channel 搜索**：去掉 `.eq("model_channel", channel)` 过滤即可
- **新增第三通道**（如 Gemini 独立通道）：只需在 `get_channel_from_model()` 加一个判断
- **channel 级别的配置差异**（如不同 channel 用不同的摘要间隔）：在 config 中加 channel 级配置即可

---

## 附录：Dream 的部署操作指南

### A. 如何把代码推送到服务器

改造完成后，你需要把代码从本地（或 Claude Code 的环境）推送到阿里云服务器。以下是步骤：

**方式一：通过 Git（推荐）**

```bash
# 1. 在 Claude Code 完成代码修改后，提交到 git
git add -A
git commit -m "feat: add model_channel isolation for multi-bot support"
git push origin main

# 2. SSH 登录你的阿里云服务器
ssh dream@47.86.37.182

# 3. 进入项目目录，拉取最新代码
cd /home/dream/memory-system
git pull origin main

# 4. 重启受影响的服务（Gateway）
pkill -f "gateway/main.py" && sleep 2 && \
cd /home/dream/memory-system/gateway && nohup python3 main.py > ../gateway.log 2>&1 &

# 5. 检查服务是否正常启动
tail -20 /home/dream/memory-system/gateway.log
curl http://localhost:8001/health
```

**方式二：通过 SCP 直接传文件（如果 git 有问题）**

```bash
# 从本地传单个文件到服务器
scp gateway/main.py dream@47.86.37.182:/home/dream/memory-system/gateway/main.py

# 传整个目录
scp -r gateway/services/ dream@47.86.37.182:/home/dream/memory-system/gateway/services/
```

### B. 数据库改造怎么执行

1. 打开浏览器，登录你的 Supabase 控制台
2. 进入 SQL Editor
3. 将本文档第三节的 SQL 语句**逐段**粘贴执行
4. 先执行 ALTER TABLE（加字段），再执行 CREATE INDEX，最后执行 RPC 函数修改
5. 每段执行后确认没有报错

### C. 如何验证改造成功

```bash
# 1. 查看 Gateway 日志，确认启动无报错
tail -50 /home/dream/memory-system/gateway.log

# 2. 健康检查
curl http://localhost:8001/health

# 3. 在 Kelivo App 中用 DeepSeek Bot 发一条消息
#    然后在 Supabase 中查看 conversations 表最新一条
#    确认 model_channel = 'deepseek'

# 4. 在 Kelivo App 中用 Claude Bot 发一条消息
#    确认 model_channel = 'claude'
```

---

*文档结束。如有疑问请随时问 Dream 或在 Claude Code 中提出。*

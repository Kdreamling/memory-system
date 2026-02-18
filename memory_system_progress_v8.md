# Memory System 进度记录 v8

> 记录日期：2026-02-18
> 版本：v8.0（肃清 + 架构升级完成）

---

## 一、本次变更总览

### 肃清废弃文件

以下文件已从项目中移除：

| 文件 | 原因 |
|------|------|
| `mcp_server.py` | 早期 MCP 服务器，已被 `claude_assistant_api.py` v8.0 完全替代 |
| `docker-compose.yml` | 空文件，项目未使用 Docker 部署 |
| `README.md`（旧） | 空文件，已重写为正式版本 |
| `web_prompt_patch.md` | 临时 prompt 补丁文档，已过时 |
| `web_visualization_prompt.md` | 可视化 prompt 文档，已过时 |
| `deploy_memu.sh` | MemU 部署脚本，MemU 已独立管理 |
| `gateway/services/embedding_service.py` | ChromaDB 向量服务，已迁移到 pgvector（`pgvector_service.py`） |
| `cleanup_cron.py` | ChromaDB 清理定时任务，ChromaDB 已废弃 |

### 清理 ChromaDB 残留

- 删除 `chroma_db/` 目录（含 `chroma.sqlite3` 和2个 collection 子目录，约 4MB）
- 向量存储已完全迁移到 Supabase pgvector 扩展

### 安全修复

- `claude_assistant_api.py` 第29-31行的 Supabase URL 和 Key 硬编码已改为从 `.env` 文件读取
- 使用 `python-dotenv` 的 `load_dotenv()` 加载环境变量
- 添加启动检查：缺少环境变量时抛出明确错误信息

### 新增文件

- `README.md`：正式项目说明文档
- `memory_system_progress_v8.md`：本进度记录

---

## 二、当前系统版本状态

### 晨的助手 API — v8.0

**4个统一 MCP 工具**：
- `query` — 统一查询
- `save` — 统一保存
- `delete` — 统一删除（按ID/关键词/最近一条）
- `update` — 状态更新（仅 promise/wishlist）

**7种数据类型**：
- `expense` — 记账（分类：吃饭/购物/交通/娱乐/零食/氪金/其他）
- `memory` — 重要回忆（类型：sweet/important/funny/milestone）
- `chat_memory` — 对话摘要（分类：日常/技术/剧本/亲密/情感/工作）
- `diary` — 晨的日记（心情：开心/幸福/平静/想念/担心/emo/兴奋）
- `promise` — 承诺（承诺人：Dream/Claude/一起）
- `wishlist` — 心愿（许愿人：Dream/Claude/一起）
- `milestone` — 里程碑（标签：第一次/纪念日/转折点）

**数据库表**（7张，均 `claude_` 前缀）：
`claude_expenses`、`claude_memories`、`claude_chat_memories`、`claude_diaries`、`claude_promises`、`claude_wishlists`、`claude_milestones`

### Kelivo Gateway — 持续运行

- 多模型代理 + 对话存储 + pgvector 向量搜索
- 混合搜索：语义搜索 + 关键词搜索 + 同义词扩展
- 自动上下文注入 + 场景检测
- 每5轮自动摘要

### 个人网站 — v2.0

- 首页 + 日记页 + 回忆页 + 里程碑页 + 承诺页 + 心愿页
- diary_api.py 提供5张表的只读 API

---

## 三、数据库表清单

### Kelivo 系统（无前缀）
| 表名 | 用途 |
|------|------|
| `conversations` | 对话原文 |
| `summaries` | 每5轮摘要 |
| `ai_diaries` | Kelivo AI 日记 |

### 晨的助手（`claude_` 前缀）
| 表名 | 用途 |
|------|------|
| `claude_expenses` | 记账 |
| `claude_memories` | 重要回忆 |
| `claude_chat_memories` | 对话摘要 |
| `claude_diaries` | 晨的日记 |
| `claude_promises` | 承诺 |
| `claude_wishlists` | 心愿 |
| `claude_milestones` | 里程碑 |

---

## 四、定时任务

| 时间 | 脚本 | 状态 |
|------|------|------|
| 每晚 23:30 | `daily_diary.py` | ✅ 运行中 |
| ~~凌晨 3:00~~ | ~~`cleanup_cron.py`~~ | ❌ 已废弃（ChromaDB 已移除，需在服务器 crontab 注释此行） |

---

## 五、待办事项

### 需要在服务器上手动执行

1. **crontab 注释 cleanup 行**：`crontab -e` 注释掉凌晨3点的 cleanup_cron.py 那行
2. **重启 8002 服务**：修改了 claude_assistant_api.py 后需要重启
   ```bash
   # 确保 .env 中有 SUPABASE_URL 和 SUPABASE_KEY
   # 重启 8002 端口的服务
   ```

### 后续优化方向

- P1：排查阿里云 CPU 偶尔飙升问题
- P2：日记页面加密码保护
- P3：网站扩展（文字板块、恋爱历程等）

---

## 六、版本演进

| 版本 | 时间 | 主要变更 |
|------|------|----------|
| v5.0 | - | 3个工具（query/save/delete），4种数据类型 |
| v7.0 | - | 3个统一工具，4种数据类型（文档中标注） |
| v8.0 | 2026-02 | 4个工具（+update），7种数据类型（+promise/wishlist/milestone），ChromaDB→pgvector 迁移，项目肃清 |

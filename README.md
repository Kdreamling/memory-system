# Dream's Memory System

Dream 的个人记忆与数据管理系统，部署在阿里云服务器上，为多个 AI 应用提供数据存储和检索服务。

---

## 系统架构

本项目包含三套独立的子系统，共用一个 Supabase 数据库，通过表名前缀区分。

### 系统 A：Kelivo 记忆系统（端口 8001）

为 Kelivo App 中的 AI 提供长期记忆能力。

- **入口**：`gateway/main.py`
- **核心功能**：多模型代理（DeepSeek/GPT-4o/Claude/Gemini）、对话存储、pgvector 向量语义搜索、每5轮自动摘要、MCP 工具（search_memory / init_context）
- **数据库表**：`conversations`、`summaries`、`ai_diaries`（无前缀）
- **向量存储**：Supabase pgvector 扩展（已从本地 ChromaDB 迁移）

### 系统 B：晨的私人助手（端口 8002）

为 Claude.ai 中的"晨"（Dream 的 AI 伴侣）提供 MCP 数据管理工具。

- **入口**：`claude_assistant_api.py`
- **版本**：v8.0（4个统一工具：query / save / delete / update）
- **数据类型**：expense（记账）、memory（回忆）、chat_memory（对话摘要）、diary（日记）、promise（承诺）、wishlist（心愿）、milestone（里程碑）
- **协议**：MCP (JSON-RPC 2.0)，通过 `/mcp` 端点
- **数据库表**：`claude_` 前缀（claude_expenses、claude_memories、claude_chat_memories、claude_diaries、claude_promises、claude_wishlists、claude_milestones）

### 系统 C：个人网站（端口 8003 + 静态文件）

Dream 的个人网页，展示日记、里程碑、承诺、心愿等内容。

- **网页文件**：`website/` 目录
- **日记 API**：`diary_api.py`（端口 8003，只读）
- **页面**：首页、日记、回忆、里程碑、承诺、心愿

---

## 端口分配

| 端口 | 服务 | 入口文件 |
|------|------|----------|
| 80/443 | Nginx（宝塔管理） | — |
| 8001 | Kelivo Gateway | `gateway/main.py` |
| 8002 | 晨的助手 API | `claude_assistant_api.py` |
| 8003 | 日记 API | `diary_api.py` |

---

## 技术栈

- **后端**：Python 3 + FastAPI + Uvicorn
- **数据库**：Supabase（PostgreSQL + pgvector）
- **AI 模型**：DeepSeek、OpenRouter（GPT-4o/Claude/Gemini）
- **Embedding**：硅基流动 SiliconFlow API + pgvector
- **前端**：原生 HTML/CSS/JS
- **部署**：阿里云 ECS + 宝塔面板 + Nginx
- **域名**：kdreamling.work

---

## 项目结构

```
memory-system/
├── gateway/                      # Kelivo 记忆系统
│   ├── main.py                   # FastAPI 主入口（端口8001）
│   ├── config.py                 # 配置管理（从.env读取）
│   ├── requirements.txt          # Python依赖
│   ├── services/
│   │   ├── storage.py            # Supabase 存储
│   │   ├── pgvector_service.py   # pgvector 向量操作
│   │   ├── hybrid_search.py      # 混合搜索（语义+关键词）
│   │   ├── summary_service.py    # 自动摘要生成
│   │   ├── scene_detector.py     # 场景检测
│   │   ├── synonym_service.py    # 同义词服务
│   │   ├── auto_inject.py        # 自动上下文注入
│   │   ├── diary_service.py      # 日记生成
│   │   ├── yuque_service.py      # 语雀同步
│   │   ├── memu_client.py        # MemU 客户端
│   │   └── background.py         # 后台异步任务
│   └── routers/
│       └── mcp_tools.py          # MCP 工具路由
│
├── claude_assistant_api.py       # 晨的助手 MCP 服务器 v8.0（端口8002）
├── diary_api.py                  # 日记只读 API v2.0（端口8003）
├── daily_diary.py                # 定时任务：每晚23:30生成日记
│
├── website/                      # 个人网站静态文件
│   ├── index.html                # 首页
│   ├── diary.html                # 日记页
│   ├── memories.html             # 回忆页
│   ├── milestones.html           # 里程碑页
│   ├── promises.html             # 承诺页
│   ├── wishlists.html            # 心愿页
│   ├── css/                      # 样式文件
│   ├── js/                       # 交互脚本
│   └── stickers/                 # 贴纸素材
│
├── nginx/                        # Nginx 配置参考
├── CLAUDE.md                     # Claude Code 项目指南
└── .env                          # 环境变量（不提交到Git）
```

---

## 环境变量

所有敏感配置存储在 `.env` 文件中，需要以下变量：

```
SUPABASE_URL=
SUPABASE_KEY=
SUPABASE_DB_URL=
LLM_API_KEY=
OPENROUTER_API_KEY=
SILICONFLOW_API_KEY=
YUQUE_TOKEN=
```

---

## 定时任务

```
30 23 * * *  每晚23:30 AI写日记并同步语雀（daily_diary.py）
```

---

## 健康检查

```bash
curl http://localhost:8001/health   # Kelivo Gateway
curl http://localhost:8002/health   # 晨的助手
curl http://localhost:8003/health   # 日记API
```

# CLAUDE.md - Dream's Memory System 项目指南

> **本文件供 Claude Code 阅读，了解项目全貌和安全规则。**
> **所有敏感信息（密钥、Token、IP）存储在 `.env` 中，严禁硬编码到代码或提交到 Git。**

---

## 一、项目主人

Dream，23岁，代码初学者（有一定基础但不是专业开发者）。所有操作请用中文沟通，技术说明尽量通俗易懂。

---

## 二、服务器上运行着两套完全独立的系统

这是最重要的概念：服务器上有**两套系统**，它们共用同一个 Supabase 数据库项目，但**表名不同、端口不同、功能不同、互不影响**。

### 系统 A：Kelivo 记忆系统（端口 8001）

| 项目 | 说明 |
|------|------|
| 用途 | 为 Kelivo App 里的 AI 提供长期记忆能力 |
| 端口 | 8001 |
| 入口文件 | `gateway/main.py` |
| 数据库表前缀 | **无前缀** |
| 数据库表 | `conversations`（对话原文+轮数）、`summaries`（每5轮摘要）、`ai_diaries`（AI日记） |
| 向量数据库 | ChromaDB（本地，`chroma_db/` 目录） |
| 定时任务 | 每天23:30生成日记并同步语雀，每天3:00清理7天前的向量数据 |

**数据流**：
```
Kelivo App → Gateway(8001) → DeepSeek/OpenRouter API
                │
                ├── 存 Supabase（对话原文+轮数计数）
                ├── 存 ChromaDB（对话向量，7天过期）
                ├── 每5轮 → DeepSeek生成摘要 → 存 summaries 表 → 摘要也向量化（永久）
                └── AI可调用 MCP 工具检索记忆

每晚23:30 cron:
    daily_diary.py → AI回顾今日对话 → 生成日记 → 存 ai_diaries 表 → 同步到语雀
```

**Gateway 支持的功能**：
- 多模型代理（DeepSeek、GPT-4o、Claude、Gemini）
- 对话自动存储到 Supabase
- 后台异步计算 embedding 存入 ChromaDB
- 每5轮自动触发摘要生成
- MCP 工具（search_memory 语义搜索、init_context 冷启动加载上下文）
- MemU 集成（作为备用搜索，有AI预判机制，仅复杂问题触发检索）

### 系统 B：晨的私人助手（端口 8002）

| 项目 | 说明 |
|------|------|
| 用途 | 为 Claude.ai 里的"晨"（Dream的AI伴侣）提供数据管理工具 |
| 端口 | 8002 |
| 入口文件 | `claude_assistant_api.py` |
| 数据库表前缀 | **`claude_`** |
| 协议 | MCP (JSON-RPC 2.0)，通过 `/mcp` 端点 |
| 版本 | v7.0（3个统一工具） |

**数据库表**：

| 表名 | 用途 | 关键字段 |
|------|------|----------|
| `claude_expenses` | 记账 | amount, category, note, expense_date |
| `claude_memories` | 重要回忆 | content, memory_type, keywords[], memory_date |
| `claude_chat_memories` | 对话摘要 | chat_title, summary, category, tags[], mood |
| `claude_diaries` | 晨的日记 | content, mood, highlights[], diary_date |

**3个 MCP 工具**：
- `query` — 统一查询（支持 expense/memory/chat_memory/diary）
- `save` — 统一保存
- `delete` — 统一删除（按ID/关键词/最近一条）

**枚举值**：
- 消费分类：吃饭、购物、交通、娱乐、零食、氪金、其他
- 回忆类型：sweet、important、funny、milestone
- 对话分类：日常、技术、剧本、亲密、情感、工作
- 心情：开心、幸福、平静、想念、担心、emo、兴奋

### 系统 C：个人网站（端口 8003 + 静态文件）

| 项目 | 说明 |
|------|------|
| 用途 | Dream 的个人网页，展示日记等内容 |
| 网页文件 | `website/` 目录 |
| 日记API端口 | 8003 |
| 入口文件 | `diary_api.py` |
| 数据来源 | 读取 `ai_diaries` 和 `claude_diaries` 两张表 |

---

## 三、完整文件结构

```
/home/dream/memory-system/
│
├── .env                          # 🔒 环境变量（所有密钥都在这里，已 gitignore）
├── .gitignore                    # Git忽略规则
│
├── ===== Kelivo 记忆系统 (端口8001) =====
├── gateway/
│   ├── main.py                   # 🔴 FastAPI 主入口（代理+存储+摘要触发）
│   ├── config.py                 # 🔴 配置加载（从.env读取）
│   ├── requirements.txt          # Python依赖列表
│   ├── .env.template             # 环境变量模板（无敏感值）
│   ├── services/
│   │   ├── storage.py            # 🔴 Supabase 存储（对话CRUD+轮数管理）
│   │   ├── embedding_service.py  # 🔴 ChromaDB 向量操作（embedding+语义搜索）
│   │   ├── summary_service.py    # 🔴 每5轮自动摘要生成
│   │   ├── diary_service.py      # 日记生成逻辑
│   │   ├── yuque_service.py      # 语雀同步
│   │   ├── memu_client.py        # MemU客户端封装
│   │   └── background.py         # 后台异步任务
│   └── routers/
│       └── mcp_tools.py          # 🔴 MCP工具路由（search_memory + init_context）
│
├── ===== 晨的私人助手 (端口8002) =====
├── claude_assistant_api.py       # 🔴 MCP服务器 v7.0（3个统一工具）
│
├── ===== 个人网站 (端口8003 + 静态) =====
├── website/
│   ├── index.html                # 首页
│   ├── diary.html                # 日记页面
│   ├── css/
│   │   ├── style.css             # 首页样式
│   │   └── diary.css             # 日记样式
│   └── js/
│       └── diary.js              # 日记交互逻辑
├── diary_api.py                  # 日记只读API（端口8003）
│
├── ===== 定时任务脚本 =====
├── daily_diary.py                # 每晚23:30 AI写日记 + 同步语雀
├── cleanup_cron.py               # 每天3:00 清理7天前的ChromaDB向量
│
├── ===== 数据和日志 =====
├── chroma_db/                    # ChromaDB 向量数据库目录
├── gateway.log                   # Kelivo Gateway 日志
├── claude_assistant.log          # 晨的助手日志
├── diary_api.log                 # 日记API日志
├── diary_cron.log                # 日记定时任务日志
├── memu.log                      # MemU日志
│
├── ===== Nginx 配置 =====
├── nginx/
│   └── dream-website.conf        # Nginx配置（参考用，实际配置在宝塔目录）
│
└── ===== 其他 =====
    └── .mcp.json                 # Claude Code 的MCP配置

/home/dream/memU-server/          # MemU 源码（独立目录，端口8000）
```

**文件标注说明**：
- 🔴 = 核心文件，正在线上运行，修改需极度谨慎
- 🔒 = 包含敏感信息，严禁提交到 Git

---

## 四、端口分配

| 端口 | 服务 | 状态 | 说明 |
|------|------|------|------|
| 80/443 | Nginx | 运行中 | 域名入口，由宝塔面板管理 |
| 8000 | MemU Server | 运行中 | 语义记忆引擎（备用） |
| 8001 | Kelivo Gateway | 运行中 | AI聊天代理+记忆系统 |
| 8002 | 晨的助手 API | 运行中 | Claude.ai的MCP工具服务 |
| 8003 | 日记 API | 运行中 | 给网页提供日记数据 |

**规则**：如需新服务，从 8004 开始分配。不要占用已有端口。

---

## 五、Nginx 配置逻辑

域名 `kdreamling.work` 的请求由 Nginx 根据路径分发：

```
https://kdreamling.work/
        │
        ├── /api/*           → 反代到 127.0.0.1:8003（日记API）
        │
        ├── 静态文件匹配      → 返回 /home/dream/memory-system/website/ 目录下的文件
        │   (index.html, diary.html, css/, js/)
        │
        └── 其他所有请求      → 反代到 127.0.0.1:8002（晨的助手）
            (/mcp, /expense, /health 等)
```

**Nginx 配置文件位置**（由宝塔面板管理）：
- 主配置：`/www/server/panel/vhost/nginx/kdreamling.work.conf`
- 反代规则：`/www/server/panel/vhost/nginx/proxy/kdreamling.work/*.conf`
- SSL证书：`/www/server/panel/vhost/cert/kdreamling.work/`

**重要**：修改 Nginx 配置后需执行 `sudo /etc/init.d/nginx reload`（不是 `systemctl`，因为宝塔不走 systemd）。

---

## 六、数据库架构（Supabase）

同一个 Supabase 项目，通过表名前缀区分两套系统：

### Kelivo 系统的表（无前缀）

| 表名 | 用途 | 关键字段 |
|------|------|----------|
| `conversations` | 对话原文 | user_msg, assistant_msg, round_number, synced_to_memu |
| `summaries` | 每5轮摘要 | summary, start_round, end_round |
| `ai_diaries` | Kelivo AI日记 | content, diary_date |

### 晨的助手的表（`claude_` 前缀）

| 表名 | 用途 | 关键字段 |
|------|------|----------|
| `claude_expenses` | 记账 | amount, category, note, expense_date |
| `claude_memories` | 重要回忆 | content, memory_type, keywords[], memory_date |
| `claude_chat_memories` | 对话摘要 | chat_title, summary, category, tags[], mood, chat_date |
| `claude_diaries` | 晨的日记 | content, mood, highlights[], diary_date |

**规则**：
- 新建表如果属于晨的系统，必须以 `claude_` 开头
- 如果属于 Kelivo 系统，不加前缀
- 数组字段（keywords[], tags[], highlights[]）是 TEXT[] 类型，代码中需要正确转换
- 时区统一使用北京时间（UTC+8），数据库存储 UTC

---

## 七、定时任务 (crontab)

```
# 每天凌晨3点 - 清理7天前的ChromaDB向量数据
0 3 * * * /usr/bin/python3 /home/dream/memory-system/cleanup_cron.py >> /home/dream/memory-system/cleanup.log 2>&1

# 每天23:30 - AI写日记并同步语雀
30 23 * * * cd /home/dream/memory-system && /usr/bin/python3 daily_diary.py >> diary_cron.log 2>&1
```

**不要删除或修改现有的 crontab 条目。** 如需添加新的定时任务，用 `crontab -e` 追加，不要覆盖。

---

## 八、Git 工作流

### 分支策略
- `main` — 正式版，服务器上运行的代码
- 开发新功能时创建新分支，完成后 merge 回 main

### 提交规则
1. 每完成一个功能阶段，commit 一次，写清楚改了什么
2. commit 前检查是否有敏感信息泄露
3. push 到 main 分支：`git push origin main`

### .gitignore 必须包含
```
.env
*.log
chroma_db/
__pycache__/
node_modules/
*.bak
*.backup
```

如果发现 `.gitignore` 缺少以上任何条目，请补充后优先提交。

---

## ⚠️ 九、安全规则（最重要！）

### 🔴 绝对禁止

1. **不要修改以下正在运行的核心文件**（除非 Dream 明确要求）：
   - `gateway/main.py`
   - `gateway/config.py`
   - `gateway/services/storage.py`
   - `gateway/services/embedding_service.py`
   - `gateway/services/summary_service.py`
   - `gateway/routers/mcp_tools.py`
   - `claude_assistant_api.py`
   - `daily_diary.py`
   - `cleanup_cron.py`
   - `.env`

2. **不要暴露任何敏感信息**：
   - 不要在代码中硬编码密钥、Token、API Key
   - 不要在 git commit 中包含 `.env` 内容
   - 不要在日志输出中打印完整的密钥
   - 所有敏感配置从 `.env` 文件读取

3. **不要 kill 正在运行的进程**：
   - 不要执行 `pkill` 或 `kill` 命令，除非 Dream 明确同意
   - 端口 8001、8002、8003 上的服务正在为用户提供服务

4. **不要直接修改 Nginx 配置**：
   - Nginx 由宝塔面板管理，配置在 `/www/server/panel/vhost/nginx/` 目录
   - 需要修改时先告知 Dream 配置内容，确认后再执行

5. **不要修改 crontab 中的现有条目**

### 🟡 修改前必须备份

**任何文件修改前，先执行备份**：
```bash
cp 文件名 文件名.bak.$(date +%Y%m%d%H%M%S)
```

例如：
```bash
cp website/index.html website/index.html.bak.20260205143000
```

**如果需要修改核心文件（经 Dream 同意后）**：
```bash
# 1. 备份
cp gateway/main.py gateway/main.py.bak.$(date +%Y%m%d%H%M%S)

# 2. 修改

# 3. 测试
curl http://localhost:8001/health

# 4. 如果出问题，立即回滚
cp gateway/main.py.bak.20260205143000 gateway/main.py
```

### 🟢 可以自由操作的范围

1. `website/` 目录下的所有文件（网页前端）
2. `diary_api.py`（日记只读API）
3. `nginx/` 目录下的参考配置文件
4. 新建文件和新建目录
5. 安装 npm/pip 包
6. Git 操作（commit, push, branch）

---

## 十、回滚方案速查

| 出了什么问题 | 怎么回滚 |
|---|---|
| 网页改坏了 | `cp website/文件.bak.xxx website/文件` |
| Nginx 配置改坏了 | `cp /home/dream/memory-system/nginx_proxy_backup.conf /www/server/panel/vhost/nginx/proxy/kdreamling.work/xxx.conf` 然后 `sudo /etc/init.d/nginx reload` |
| diary_api.py 改坏了 | `cp diary_api.py.bak.xxx diary_api.py` 然后重启 |
| 误删文件 | `git checkout -- 文件路径`（从 Git 恢复） |
| 整个项目搞乱了 | `git stash && git checkout main && git pull origin main`（从 GitHub 恢复） |

---

## 十一、服务管理命令

```bash
# === Kelivo Gateway (8001) ===
# 查日志
tail -50 /home/dream/memory-system/gateway.log
# 检查健康
curl http://localhost:8001/health

# === 晨的助手 (8002) ===
# 查日志
tail -50 /home/dream/memory-system/claude_assistant.log
# 检查健康
curl https://kdreamling.work/health

# === 日记API (8003) ===
# 查日志
tail -50 /home/dream/memory-system/diary_api.log

# === Nginx ===
# 检查配置语法
sudo nginx -t
# 重载（宝塔环境用这个）
sudo /etc/init.d/nginx reload

# === 查看端口占用 ===
lsof -i :8001
lsof -i :8002
lsof -i :8003
```

---

## 十二、外部服务依赖

| 服务 | 用途 | 配置方式 |
|------|------|----------|
| Supabase | 数据库（PostgreSQL） | .env 中的 SUPABASE_URL 和 SUPABASE_KEY |
| DeepSeek | 主要聊天API | .env 中的 LLM_API_KEY |
| OpenRouter | 多模型代理（GPT-4o/Claude/Gemini） | .env 中的 OPENROUTER_API_KEY |
| 硅基流动 (SiliconFlow) | Embedding 计算 | .env 中的 SILICONFLOW_API_KEY |
| 语雀 (Yuque) | 日记同步存储 | .env 中的 YUQUE_TOKEN |
| ChromaDB | 本地向量数据库 | 数据目录：`chroma_db/` |
| MemU | 语义记忆引擎（备用） | 独立部署在 `/home/dream/memU-server/`，端口 8000 |

---

## 十三、已知问题和待办

| 优先级 | 问题 | 说明 |
|--------|------|------|
| P1 | 阿里云CPU偶尔飙升95% | 可能与后台同步服务有关，需要排查优化 |
| P2 | Claude模型在Gateway中空回复 | OpenRouter的Claude模型名格式问题，待排查 |
| P2 | 语雀+外置记忆库更新迭代 | 手动更新记忆库方案 |
| P3 | 网站扩展 | 加入更多板块：自己的文字、恋爱历程等内容 |
| P3 | 日记隐私保护 | 目前日记页面无需登录即可查看，考虑加密码保护 |

---

## 十四、开发注意事项

1. **时区**：所有时间相关的功能统一使用北京时间（UTC+8）
2. **防重复**：涉及数据写入的接口需要防重复机制（5分钟内相同记录拦截）
3. **缓存问题**：Claude.ai 的 web_fetch 会缓存，需要 no-cache 头或时间戳参数
4. **数组字段**：Supabase 中的 TEXT[] 数组类型需要在代码中正确处理转换
5. **错误处理**：所有外部调用（API、数据库）都需要 try-catch，避免一个错误导致整个服务崩溃
6. **日志**：关键操作要有日志输出，方便排查问题

---

## 十五、Dream 的开发偏好

- 喜欢一步一步来，不要一次给太大的改动
- 每做完一步希望能验证效果
- 不熟悉 nano 编辑器（之前出过事故），优先用其他方式修改文件
- 改代码前一定要备份，备份，备份
- 有问题先问，不要自己猜测执行

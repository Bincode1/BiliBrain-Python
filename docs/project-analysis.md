# BiliBrain 系统分析报告

## 一、系统定位

**BiliBrain** 是一个围绕 B站收藏夹构建的 **个人视频知识工作台**。它将用户收藏的视频转化为可搜索、可摘要、可问答的知识库，核心能力包括：

- **视频采集** — 从 B站收藏夹自动同步视频元数据与音频
- **语音转写 (ASR)** — 使用 faster-whisper 对音频进行中文语音识别
- **智能摘要** — 自动生成单视频 / 整文件夹的视频摘要
- **RAG 问答** — 基于向量检索 + BM25 混合搜索的知识库问答
- **AI Agent** — 带工具调用、技能激活、人机协同审批的统一智能代理

---

## 二、整体架构

```
┌─────────────────────────────────────────────────────┐
│                   Vue 3 Frontend                     │
│  Chat / Library / Skills Store / Tools Store         │
│  (SSE Streaming, Pinia, Reka UI, TailwindCSS)        │
├─────────────────────────────────────────────────────┤
│                  FastAPI Backend                      │
│  ┌──────────┐  ┌──────────┐  ┌───────────────────┐  │
│  │  API层    │  │ Service层 │  │  LangGraph 工作流  │  │
│  │ 15+路由   │  │ 业务逻辑  │  │ ingestion/qa/sum  │  │
│  └──────────┘  └──────────┘  └───────────────────┘  │
│  ┌──────────┐  ┌──────────┐  ┌───────────────────┐  │
│  │ Tool系统  │  │ Skill系统 │  │  Unified Agent    │  │
│  │ 8个内置   │  │ SKILL.md │  │  ReAct循环        │  │
│  └──────────┘  └──────────┘  └───────────────────┘  │
├─────────────────────────────────────────────────────┤
│                    存储层                             │
│  SQLite (15张表)  │  ChromaDB + BM25 (混合检索)      │
│  本地音频存储      │  可插拔存储 (预留S3)              │
└─────────────────────────────────────────────────────┘
```

---

## 三、核心功能模块

| 模块 | 关键能力 |
|------|----------|
| **认证** | B站 QR 扫码登录，Cookie 持久化，WBI 签名 |
| **收藏夹管理** | 自动同步收藏夹元数据，视频搜索，标签管理 |
| **视频处理流水线** | 8 步 LangGraph 状态机：音频下载 → ASR → 分段 → 嵌入 → 入库 → 摘要 |
| **ASR 语音识别** | faster-whisper + CUDA，静音对齐分块，并发转写，重叠去重 |
| **混合检索** | ChromaDB 稠密向量 + jieba BM25 关键词，RRF 融合 (65:35) |
| **QA 问答** | 智能路由 (keyword heuristic + LLM planner)，chunk/summary 双策略，引用标注 |
| **摘要生成** | 短文本直接生成，长文本窗口化摘要-归约，transcript hash 缓存 |
| **统一 Agent** | ReAct 循环，8 个内置工具，技能系统，SSE 流式输出 |
| **工具系统** | 文件读写、命令执行、Web搜索、浏览器阅读，支持本地/Docker沙箱运行时 |
| **技能系统** | SKILL.md 声明式定义，三层来源 (内置/用户/仓库)，动态激活 |
| **人机协同 (HITL)** | 写操作和命令执行需用户审批，暂停/恢复机制 |

---

## 四、项目亮点

### 1. 精心设计的混合检索引擎

不是简单的向量搜索，而是 **Dense + BM25 + Rerank** 三阶段流水线：

- ChromaDB 余弦相似度 + jieba 中文分词 BM25
- RRF (Reciprocal Rank Fusion) 融合，权重 0.65:0.35
- 关键词重叠二次 rerank (0.85 稠密 + 0.15 关键词)

### 2. 工业级 ASR 管线

- 静音检测对齐分块 (`ffmpeg silencedetect` → `plan_silence_aligned_ranges`)
- 并发转写 + 可配置并发度 (`asyncio.Semaphore`)
- 块间重叠智能去重 (`trim_repeated_prefix`)
- CUDA 加速 + 自动 CPU 回退

### 3. 统一 Agent 架构

手写 ReAct 循环而非使用 LangGraph Agent，原因明确：**避免 msgpack 序列化问题**，获得对 HITL 审批流的完全控制。这是一个成熟的架构取舍决策。

### 4. 声明式技能系统

用 `SKILL.md` + YAML frontmatter 定义技能，支持：

- 三层来源：`builtin_skills/` / `~/.bilibrain/skills/` / `.agents/skills/`
- 每个技能声明允许使用的工具列表
- 运行时动态激活/停用，状态持久化到数据库

### 5. 内存感知的对话系统

不是简单截断历史，而是 **LLM 驱动的结构化记忆压缩**：

- 超过 50k tokens 自动触发压缩
- 压缩输出包含"活跃目标"、"已确认结论"、"术语映射"等结构化字段
- 上下文统计跟踪避免重复压缩

### 6. 完整的工具安全模型

- **策略层**：命令前缀黑白名单
- **审批机制**：写/执行操作必须用户确认
- **隔离运行时**：本地子进程或 Docker 沙箱 (含资源限制)
- **工作区隔离**：每个会话独立文件系统空间

### 7. 工程化的摄取调度器

- 任务去重、Worker ID 分配、心跳检测
- 可配置并发度、过期任务自动标记
- 支持独立 worker 进程 (`ingestion_worker.py`)

### 8. 前端体验

- SSE 实时流式输出 (token/sources/reasoning/tool/approval 多事件类型)
- 引用轮播、思维链可视化、工具执行面板
- 智能滚动 (`useSmartScroll`)
- 斜杠命令输入提示

---

## 五、技术栈总览

| 层次 | 技术 |
|------|------|
| 前端 | Vue 3.5 + Pinia 3 + Reka UI + TailwindCSS 4 + Vite 6 |
| 后端 | Python 3.13 + FastAPI + uvicorn |
| AI | LangChain + LangGraph + Qwen (DashScope) + faster-whisper |
| 向量库 | ChromaDB + rank-bm25 + jieba |
| 数据库 | SQLite (aiosqlite, WAL 模式) |
| HTTP | httpx + curl-cffi (B站浏览器伪装) |
| 部署 | 单进程 (FastAPI 托管前端静态文件) |

---

## 六、数据库设计 (15 张表)

| 表名 | 用途 |
|------|------|
| `app_state` | KV 存储 (认证 Cookie、缓存时间戳) |
| `folders` | B站收藏夹元数据 |
| `videos` | 视频元数据 (bvid, 标题, UP主, 时长, 音频引用, 标签) |
| `transcripts` | ASR 转写结果 (全文, 分段 JSON, 模型信息) |
| `video_summaries` | 生成的摘要 (含 transcript hash 用于缓存失效) |
| `video_pipeline` | 处理状态机 (audio → transcript → index) |
| `ingestion_batches` | 批量处理分组 |
| `ingestion_tasks` | 任务队列 (状态, worker 分配, 锁定) |
| `chat_conversations` | 会话元数据 (scope, folder_id, 标题) |
| `chat_messages` | 消息记录 (用户/助手, 内容, 来源 JSON) |
| `chat_conversation_memory` | 压缩后的长期记忆 |
| `chat_conversation_context_stats` | Token 计数与压缩记录 |
| `tool_workspaces` | 隔离的工作区目录 |
| `tool_calls` | 工具执行审计日志 |
| `skill_activations` | 技能激活状态 |

---

## 七、API 路由一览

### 认证

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/auth/session` | 获取当前登录状态 |
| POST | `/api/auth/qr/start` | 生成登录二维码 |
| GET | `/api/auth/qr/poll` | 轮询扫码状态 |

### 收藏夹

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/folders` | 列出所有收藏夹 |
| GET | `/api/folders/{id}/videos` | 列出收藏夹内视频 |
| GET | `/api/folders/{id}/bili-search` | 按标题搜索B站视频 |
| POST | `/api/sync` | 同步收藏夹元数据 |

### 视频

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/videos/{bvid}/transcript` | 获取转写文本 |
| GET | `/api/videos/{bvid}/summary` | 获取摘要 |
| POST | `/api/videos/{bvid}/summary` | 生成摘要 |
| GET | `/api/videos/{bvid}/process/status` | 查询处理状态 |
| POST | `/api/videos/{bvid}/process` | 启动处理流水线 |
| POST | `/api/videos/{bvid}/reset` | 重置视频处理 |
| POST | `/api/videos/{bvid}/tags` | 更新手动标签 |

### 问答 / 聊天

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/ask/stream` | SSE 流式统一 Agent 问答 |
| POST | `/api/ask` | 非流式问答 |
| GET | `/api/chat/conversations` | 列出所有会话 |
| POST | `/api/chat/conversations` | 创建新会话 |
| DELETE | `/api/chat/conversations/{id}` | 删除会话 |
| PATCH | `/api/chat/conversations/{id}` | 重命名会话 |
| GET | `/api/chat/history` | 获取聊天历史 |

### 技能

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/skills` | 列出所有技能 |
| GET | `/api/skills/{name}` | 获取技能详情 |
| POST | `/api/skills/create` | 创建新技能 |
| POST | `/api/skills/activate` | 激活技能 |
| POST | `/api/skills/deactivate` | 停用技能 |

### 工具

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/tools` | 列出所有工具 |
| GET | `/api/tools/workspaces` | 列出工作区 |
| POST | `/api/tools/workspaces` | 创建工作区 |
| POST | `/api/tools/call` | 执行工具 |

### 技能 Agent

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/skill-agent/ask/stream` | 流式技能 Agent |
| POST | `/api/skill-agent/resume` | 恢复 (HITL 审批后) |

---

## 八、总结

BiliBrain 是一个完成度相当高的个人知识管理系统。它不是简单的 LLM 套壳应用，而是在 **混合检索、ASR 管线、Agent 工具安全、对话记忆管理** 等方面都有深入工程设计的系统。特别是 Agent + 工具 + 技能 + HITL 的组合，使其不仅是一个问答系统，而是一个可扩展的 AI 工作平台。

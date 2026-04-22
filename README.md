# BiliBrain

把 B 站收藏夹变成可检索、可总结、可沉淀、可执行的个人视频知识工作台。

BiliBrain 当前不是单纯的视频摘要器，也不只是一个聊天式 RAG Demo。
按仓库现状，它更接近一个**以 B 站收藏夹为入口、由统一 Agent 驱动的 AI 视频知识工作台**。

## 当前能力

- Bilibili 扫码登录、Cookie 持久化与收藏夹同步
- LangGraph 视频处理流水线
  - 音频下载与本地/对象存储落盘
  - `ffmpeg` 静音检测切块
  - 基于 Qwen ASR 的并发转写与重叠去重
  - 文本合并、embedding 生成、ChromaDB 索引写入
  - 单视频摘要生成与 transcript hash 缓存
- 单视频 / 收藏夹 / 全局范围问答
  - `search_knowledge_base` 片段检索
  - `search_video_summaries` 摘要检索
  - SSE 流式返回答案、引用、工具事件、审批事件
- Unified Agent
  - 基于 LangGraph 编排 `load_context / model_step / approval_gate / execute_tool / finalize` 链路
  - 使用 SQLite checkpointer 保存 task graph state
  - 技能加载、动态激活、会话级 skill 审批
  - 文件 / 命令 / Web / Obsidian 工具调用
  - HITL 审批中断、参数修改与 resume 恢复执行
- 会话系统
  - 会话列表与历史
  - 任务态消息持久化
  - recent history / live prefix / memory text / workspace state 分层组装
  - 结构化记忆压缩、上下文统计快照与 workspace 运行态注入
- Vue 3 前端工作台
  - 工具执行轨迹面板
  - 审批条与“修改后继续”
  - 引用展示与范围切换

## 技术栈

当前代码实现对应的主要技术栈：

- Backend: Python 3.13, FastAPI, LangGraph, LangChain, Qwen (DashScope), Qwen ASR
- Frontend: Vue 3, Pinia, Vue Router, Reka UI, Tailwind CSS 4, Vite
- Data: SQLite, ChromaDB, local audio / object storage
- Runtime: `ffmpeg`, `httpx`, `curl-cffi`, local tool runtime, optional Docker sandbox, Obsidian CLI

说明：
README 以当前代码为准。若旧文档中出现 `MySQL / Milvus / MinIO` 等表述，请以仓库现状为准。

## 项目结构

```text
BiliBrain/
├─ frontend/                    # Vue 前端工作台
├─ bilibrain/                   # Python 后端
│  ├─ bilibrain/
│  │  ├─ ai/
│  │  ├─ api/
│  │  ├─ core/
│  │  ├─ db/
│  │  ├─ graphs/
│  │  ├─ services/
│  │  ├─ skills/
│  │  ├─ storage/
│  │  └─ tools/
│  ├─ tests/
│  ├─ .env.example
│  ├─ pyproject.toml
│  └─ start.py
├─ docs/
└─ skills/
```

## 快速开始

### 环境要求

- Python 3.13+
- Node.js 18+
- ffmpeg
- DashScope API Key

如果你要启用 Docker 沙箱工具，还需要：

- Docker

### 启动后端

```powershell
cd D:\AI_Projects\BiliBrain\bilibrain
copy .env.example .env
uv sync
python start.py
```

默认地址：

- `http://127.0.0.1:8000`
- `http://127.0.0.1:8000/api/health`

### 启动前端

```powershell
cd D:\AI_Projects\BiliBrain\frontend
npm install
npm run dev
```

默认地址：

- `http://127.0.0.1:5173`

## 常用接口

- `GET /api/auth/session`
- `POST /api/auth/qr/start`
- `GET /api/folders`
- `GET /api/folders/{folder_id}/videos`
- `POST /api/sync`
- `POST /api/videos/{bvid}/process`
- `GET /api/videos/{bvid}/transcript`
- `GET /api/videos/{bvid}/summary`
- `POST /api/ask`
- `POST /api/ask/stream`
- `POST /api/agent/resume`
- `POST /api/agent/resume/stream`
- `GET /api/skills`
- `POST /api/skills/activate`
- `GET /api/tools`
- `POST /api/tools/workspaces`
- `POST /api/tools/call`

## 测试

```powershell
cd D:\AI_Projects\BiliBrain\bilibrain
pytest
```

## 当前状态

已经具备：

- 收藏夹同步
- 视频处理、摘要与混合检索
- 统一 Agent、Skills、Tools / Workspace
- 审批恢复与多轮会话
- Obsidian 导出链路
- 前端工作台与基础测试

仍在演进：

- 更完整的开源文档
- 更清晰的部署方案
- 更丰富的工具历史与 diff 能力
- 更强的评测与策略优化链路

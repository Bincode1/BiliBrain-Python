# BiliBrain

把 B 站收藏夹变成可检索、可总结、可追问的个人视频知识工作台。

BiliBrain 的核心目标很简单：

- 把收藏夹里的视频元数据同步到本地
- 对视频做音频提取、ASR 转写、切块和索引
- 为单视频生成摘要
- 围绕视频、收藏夹或全局知识库发起问答
- 在同一个工作台里叠加 skills、workspace tools 和 agent 能力

它不是单纯的视频摘要器，也不只是一个聊天式 RAG Demo。  
更准确地说，它是一个**以 B 站收藏夹为入口的 AI 视频知识库与工作台**。

## 当前能力

- Bilibili 扫码登录与收藏夹同步
- 视频处理流水线
  - 音频下载
  - ASR 转写
  - 文本切块
  - embedding 与索引写入
  - 单视频摘要生成
- 视频 / 收藏夹 / 全局范围问答
- 会话历史、会话列表、会话记忆压缩
- Skills 系统
- Workspace tools 与审批机制
- Vue 前端工作台

## 技术栈

当前代码实现对应的主要技术栈：

- Backend: FastAPI, LangGraph, LangChain, DashScope Qwen, faster-whisper
- Frontend: Vue 3, Pinia, Vue Router, Vite, Tailwind CSS
- Data: SQLite, ChromaDB, local audio storage
- Runtime: ffmpeg, local tool runtime, optional Docker sandbox

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
- `GET /api/skills`
- `POST /api/skills/activate`
- `GET /api/tools`
- `POST /api/tools/call`

## 测试

```powershell
cd D:\AI_Projects\BiliBrain\bilibrain
pytest
```

## 当前状态

已经具备：

- 收藏夹同步
- 视频处理与索引
- 摘要与问答
- Skills
- Tools / Workspace
- 前端工作台
- 测试基础

仍在演进：

- 更完整的开源文档
- 更清晰的部署方案
- 更完善的审批流
- 更多工具与导出能力


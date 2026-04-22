# BiliBrain 系统分析报告

## 一、当前定位

**BiliBrain** 当前不是单纯的“视频摘要工具”或“聊天式 RAG Demo”，而是一个以 **B 站收藏夹为入口** 的个人视频知识工作台。

按实际代码实现，它已经形成了三条明确主线：

- **视频知识摄取**：收藏夹同步、音频下载、ASR 转写、切块、向量化、摘要生成
- **统一 Agent 问答**：围绕单视频、收藏夹或全局知识库做检索、总结、追问与工具调用
- **知识沉淀与执行**：通过 skills、workspace tools、审批恢复和 Obsidian 导出，把问答扩展成可执行工作流

当前系统的重点不再只是“回答问题”，而是把视频内容沉淀成一个可检索、可追问、可导出的本地知识环境。

---

## 二、整体架构

```text
┌──────────────────────────────────────────────────────────┐
│                       Vue 3 Frontend                     │
│  Chat / Folder Workspace / Agent Panel / Approval Bar    │
│  SSE Streaming / Task Timeline / Sources / Tool Output   │
├──────────────────────────────────────────────────────────┤
│                      FastAPI Backend                     │
│  API Routes  │ Services │ LangGraph Graphs              │
│              │          │ - ingestion                   │
│              │          │ - summary                     │
│              │          │ - unified_agent               │
├──────────────────────────────────────────────────────────┤
│                 Tool / Skill / Agent Runtime             │
│  ToolService + Workspace + Policy + Runtime Adapter      │
│  SkillService + SKILL.md + LangGraph checkpoint/interrupt│
├──────────────────────────────────────────────────────────┤
│                         Storage                          │
│  SQLite / Chat Store / ChromaDB / Audio Storage          │
└──────────────────────────────────────────────────────────┘
```

---

## 三、核心链路

### 1. 收藏夹同步与视频摄取

系统从 Bilibili 扫码登录开始，持久化 Cookie 后同步收藏夹与视频元数据。

对单个视频的处理由 `graphs/ingestion` 驱动，核心步骤是：

1. 下载音频并写入音频存储
2. 用 `ffmpeg` 做静音检测和切块
3. 基于 Qwen ASR 并发转写每个音频块
4. 对转写结果做重叠去重和分段合并
5. 生成 embedding 并写入 ChromaDB
6. 触发单视频摘要生成

这一条链路已经不是串行脚本，而是带状态回写、阶段进度和失败暴露的 LangGraph 流程。

### 2. 摘要链路

`graphs/summary` 负责单视频摘要生成，策略很清晰：

- 文本较短时，直接对合并后的 transcript 生成摘要
- 文本较长时，先按窗口生成局部摘要，再做一次归约
- 用 `transcript_hash` 做缓存校验，避免重复生成

这说明摘要不是一个“顺手附加功能”，而是摄取链路中的正式产物。

### 3. 混合检索与问答范围

当前知识检索建立在 `LocalVectorStore` 上，核心设计是：

- **ChromaDB 稠密检索**
- **jieba + BM25 关键词检索**
- **RRF 融合，权重 0.65 / 0.35**
- 在视频 / 收藏夹 / 全局三个范围内做过滤

同时系统暴露了两类检索工具：

- `search_knowledge_base`：面向 chunk 级细节问题
- `search_video_summaries`：面向跨视频总结、对比、概览问题

也就是说，问答链路已经明确区分“查细节”和“做概括”两类任务，而不是把所有问题都塞给同一套上下文拼接逻辑。

### 4. Unified Agent 主链路

当前 `/api/ask` 和 `/api/ask/stream` 已经不再走旧式单一 QA 函数，而是进入基于 LangGraph 的 unified agent graph。

图结构是显式拆开的：

```text
START
  -> load_context
  -> model_step
  -> select_next_tool_call
  -> approval_gate
  -> execute_tool
  -> model_step / finalize_answer / finalize_error / finalize_rejected
  -> END
```

这条链路的关键点有：

- `load_context` 负责解析当前视频 / 收藏夹 / 全局范围，组装系统提示词、近期历史、结构化记忆和 workspace 运行态
- `model_step` 使用 Qwen 模型并绑定检索工具、skill 工具和 workspace tools，流式解析模型输出和 tool call chunks
- `select_next_tool_call` 将模型一次返回的多个 tool call 拆成队列逐个执行
- `approval_gate` 对 `run_command/write_file/append_file/make_dir/obsidian_write_note/skill` 等敏感动作触发 LangGraph `interrupt`
- `execute_tool` 统一执行工具，并把工具结果作为 `ToolMessage` 回灌给模型继续推理
- `finalize_*` 统一做引用规范化、答案落库、上下文统计刷新和 task 状态收尾

运行时层面，系统还做了：

- 使用 LangGraph SQLite checkpointer 保存每个 task 的 graph state
- 用 `thread_id=task-{task_id}` 将一次用户请求绑定为可恢复任务
- 在中断时持久化 task、approval、tool_use 和 assistant placeholder
- 前端通过 `/api/agent/resume/stream` 提交 approve / edit / reject 后继续执行
- SSE 事件流把 answer、sources、tool_use、approval、task_status、skills、context 等状态实时推到前端

这意味着系统已经从“知识库问答”进入“可执行 Agent 工作台”阶段。

### 5. Tool / Skill / Approval

工具层不是直接让模型碰宿主机，而是经过统一底座：

- `ToolService`
- `Workspace`
- `Policy`
- `Runtime Adapter`

当前已注册的工具包括：

- 文件工具：`list_dir/read_file/write_file/append_file/make_dir`
- 命令工具：`run_command`
- Web 工具：`web_search/browser_read_page`
- Obsidian 工具：`obsidian_write_note/obsidian_read_note`

技能层采用 `SKILL.md + YAML frontmatter` 的声明式方式，支持：

- 多来源扫描 `SKILL.md`，并按 precedence 处理同名覆盖
- 从 frontmatter 中解析 name、description、when-to-use、allowed-tools、requires 等元信息
- 自动收集 `references/scripts/assets/agents` 等资源目录，并生成 resource map
- 动态激活 / 停用，激活状态持久化到数据库
- 模型可见性控制、会话级 skill 审批、加载记录跟踪
- 读取 skill 时注入 `BILIBRAIN_SKILL_DIR`、`resource_map`、`usage_rules`

当前 prompt 设计里，skill 的职责被限制为“流程组织”，事实来源仍必须来自工具返回结果。这一点避免了 skill 变成不可控的知识兜底。

审批机制则通过 LangGraph interrupt 实现。需要写入、执行或外部落盘时，后端会暂停任务，前端显示审批条，用户可以：

- 同意执行
- 修改参数后继续
- 拒绝

### 6. 会话上下文与结构化记忆

多轮会话不是简单截断历史，而是拆成四层：

- recent history：保留最近若干轮完整消息
- live prefix：尚未被压缩、但还可能需要进入上下文的历史片段
- memory text：由旧历史压缩出来的结构化长期记忆文本
- workspace state：运行态摘要，例如 pending approval、当前 workspace 等

结构化记忆会覆盖多个信息面，例如：

- 当前活跃目标
- 当前活跃知识范围
- 历史已完成话题
- 已确认结论
- 未解决问题
- 术语与指代
- 最近推进状态

上下文组装时，系统会：

1. 根据 token 统计判断是否需要压缩旧历史
2. 调用模型把可压缩历史写成结构化 memory text
3. 将 memory text 持久化，并刷新 context stats
4. 组合 recent history、live prefix、memory text 和必要 workspace state 注入 prompt
5. 将本次选择的 message ids、workspace keys 和 token 估算写入 context snapshot

这套设计更适合连续追问、长任务和中断恢复场景，也能解释为什么系统在审批恢复后仍然知道当前任务进展。

### 7. 前端交互形态

前端当前已经不是“一个聊天框”，而是完整工作台：

- 选择收藏夹 / 视频范围
- 查看会话历史和上下文占用
- 观看 SSE 流式回答
- 查看工具调用轨迹和技能读取记录
- 在审批条里直接编辑命令、路径、内容并恢复执行

Agent 的执行过程已经被可视化，而不是只返回一段最终文本。

---

## 四、关键实现点

### 1. 摄取链路做成了状态机，而不是脚本

`graphs/ingestion/nodes.py` 明确把视频处理拆成 audio / transcript / index / summary 多阶段，并把状态持续写回数据库。这让前端可以展示真实进度，也让失败点暴露得足够早。

### 2. ASR 采用“静音切块 + 并发转写 + 重叠去重”

当前 ASR 并不是简单整段音频直接调用模型，而是：

- `ffmpeg silencedetect` 找切分点
- 依据目标时长生成 chunk
- 并发调用 Qwen ASR
- 对相邻块的重复前缀做裁剪

这套方式明显是面向长视频稳定性做的工程设计。

### 3. 检索层是稠密与关键词混合，而不是单一向量库

`db/vector_store.py` 里对 ChromaDB 和 BM25 做并行查询，再用 RRF 融合结果。对于中文视频知识库，这比单纯 dense search 更稳，也更贴合简历里应强调的检索设计能力。

### 4. Unified Agent 已经迁到 LangGraph 图运行时

当前实现不是“手写循环凑一个 Agent”，而是：

- 用 LangGraph graph 编排 agent 节点
- 用 SQLite checkpoint 保存执行状态
- 用 interrupt 承接审批
- 用 `resume` 接口恢复执行

这是一个更接近生产形态的 agent runtime。

### 5. Obsidian 导出不是拼 CLI，而是专用工具链

`obsidian_write_note` 会：

- 解析 vault path
- 直接写入 Markdown
- 再读回校验正文是否完整

这比“调用命令然后假设成功”严谨得多，也让知识沉淀链路真正可用。

### 6. 聊天系统开始具备长期任务能力

消息、task、approval、tool_use、memory text 和 context stats 都有明确持久化结构，说明系统已经开始支持“带状态的持续任务”，而不仅是一次性问答。

---

## 五、技术栈总览

| 层次 | 当前代码对应技术 |
|------|------------------|
| 前端 | Vue 3.5、Pinia 3、Vue Router 4、Reka UI、Tailwind CSS 4、Vite 6 |
| 后端 | Python 3.13、FastAPI、uvicorn |
| AI 编排 | LangChain、LangGraph、LangGraph SQLite checkpoint |
| 模型 | Qwen（DashScope）、Qwen ASR |
| 检索 | ChromaDB、rank-bm25、jieba |
| 存储 | SQLite、音频存储服务、本地 workspace |
| 工具运行时 | local_dev、Docker sandbox、Obsidian CLI |
| 网络层 | httpx、curl-cffi |

说明：

- 仓库当前主存储与索引实现是 `SQLite + ChromaDB`，不是 `MySQL + Milvus`
- 仓库当前已有 RAGAS 依赖和评测模式配置，但主链路重点仍是摄取、检索和 unified agent

---

## 六、关键接口

### 认证与目录

- `GET /api/auth/session`
- `POST /api/auth/qr/start`
- `GET /api/folders`
- `GET /api/folders/{folder_id}/videos`
- `POST /api/sync`

### 视频处理

- `POST /api/videos/{bvid}/process`
- `GET /api/videos/{bvid}/process/status`
- `GET /api/videos/{bvid}/transcript`
- `GET /api/videos/{bvid}/summary`
- `POST /api/videos/{bvid}/summary`

### 聊天与 Agent

- `POST /api/ask`
- `POST /api/ask/stream`
- `POST /api/agent/resume`
- `POST /api/agent/resume/stream`
- `GET /api/chat/history`
- `GET /api/chat/conversations`

### 技能与工具

- `GET /api/skills`
- `POST /api/skills/activate`
- `POST /api/skills/deactivate`
- `GET /api/tools`
- `POST /api/tools/workspaces`
- `POST /api/tools/call`

---

## 七、当前结论

BiliBrain 当前最准确的描述不是“一个视频问答项目”，而是：

> 一个以 B 站收藏夹为知识入口，融合视频摄取、混合检索、统一 Agent、技能系统、工具审批和 Obsidian 导出的个人 AI 视频知识工作台。

如果用于简历，应该重点突出三件事：

1. 你把视频内容处理链路做成了稳定的 LangGraph 工作流
2. 你把检索问答扩展成了带工具和审批的统一 Agent
3. 你把回答结果进一步沉淀到了本地知识库，而不是停留在聊天窗口

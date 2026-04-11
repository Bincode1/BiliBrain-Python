# BiliBrain Skills 体系调研

**作者**: Codex  
**日期**: 2026-03-26  
**状态**: 调研结论与落地方向

## Overview

本文档调研当前支持 `skills` 的主流 agent 系统，重点关注以下问题：

- skill 到底是什么
- skill 与 tool / memory / plugin 的边界
- skill 如何被发现、激活、注入上下文
- skill 如何做范围隔离、覆盖和启停
- skill 如何与文件、命令、MCP 等工具系统协同

本文档调研的主要对象：

- Claude Code
- Codex
- deepagents
- OpenHands
- OpenClaw
- Agent Skills 通用规范

结论先说：

1. 主流系统并不把 `skills` 设计成“另一套工具运行时”。
2. `skills` 更像“按需加载的程序化知识包”或“能力 playbook”。
3. 工具系统负责“能做什么”，skills 系统负责“什么时候做、按什么流程做、需要读哪些额外资源”。
4. 当前最成熟的实现模式是 `SKILL.md + progressive disclosure + scope layering + explicit/implicit activation`。

---

## What A Skill Is

从公开实现看，skill 的最稳定定义是：

- 一个目录
- 必须包含一个 `SKILL.md`
- `SKILL.md` 由 YAML frontmatter + markdown body 构成
- frontmatter 至少包含 `name` 和 `description`
- 目录中可以带 `scripts/`、`references/`、`assets/`

这意味着 skill 不是单个 prompt，也不是单个 tool，而是一个最小可分发能力包。

### Skill vs Tool

这是实现时最容易混的地方。

- `tool`：执行动作的能力边界
  - 例如 `read_file`、`run_command`、`search_web`
- `skill`：指导 agent 如何组合工具与上下文
  - 例如“代码审查 skill”“文档抽取 skill”“竞品调研 skill”

一句话：

- tool 解决“能不能做”
- skill 解决“遇到这类任务应该怎么做”

### Skill vs Memory

多个系统都把 `skills` 和常驻记忆分开：

- `memory` / `AGENTS.md` / `CLAUDE.md`
  - 启动即注入
  - 适合一直相关的上下文
  - 如代码风格、项目约定、用户偏好
- `skills`
  - 按需加载
  - 适合任务型、较长、较专业的操作说明
  - 如“如何做网页调研”“如何做 release checklist”

### Skill vs Plugin / MCP

- `plugin` / `MCP`：提供新工具或外部能力
- `skill`：教 agent 如何使用这些能力

因此成熟系统常见组合是：

- 插件或 MCP 提供能力
- skill 提供方法论与流程

---

## The Emerging Standard

目前最接近事实标准的是 `Agent Skills` 规范。它明确把 skill 定义为目录式能力包，并强调 `progressive disclosure`。

按照该规范，agent 对 skill 的生命周期通常分五步：

1. 扫描 skills 目录
2. 解析 `SKILL.md` frontmatter
3. 把可用 skills 的简要目录暴露给模型
4. 当任务匹配时激活 skill
5. 在会话内保护 skill 上下文，避免被压缩或重复注入

规范里的几个关键点非常值得你直接借用：

- 推荐扫描 `.agents/skills/`
- 推荐只把 `name/description/location` 先注入
- 真正需要时再读完整 `SKILL.md`
- 可以通过“读文件”或专门的 `activate_skill` 工具激活
- skill 内容应避免在上下文压缩时被丢掉
- 项目级 skill 需要信任边界，防止不可信仓库注入恶意说明

这些建议非常适合你当前已经实现的 `ToolService + Workspace + Policy + Runtime` 架构。

---

## System Survey

## Claude Code

Claude Code 的 skills 已经是比较完整的产品形态。

它的核心特点：

- skill 放在 `.claude/skills/`
- 每个 skill 必须包含 `SKILL.md`
- `name` 变成 slash command
- `description` 用于模型自动判断是否触发
- 支持嵌套目录自动发现，适合 monorepo
- 支持 supporting files，例如模板、示例、脚本
- 可以显式调用，也可以让模型隐式触发

值得注意的设计点：

- Claude Code 明确把 skill 分成两类内容：
  - reference content
  - task content
- 对“只想手动触发”的 skill，支持 `disable-model-invocation: true`
- 强调 supporting files 必须由 `SKILL.md` 明确引用，而不是默认全部塞进上下文

这说明 Claude Code 的核心不是“技能市场”，而是“按需读入的本地工作说明书体系”。

对你最有价值的地方：

- 目录级发现
- 支持工作区局部 skill
- instruction-first
- 显式/隐式触发分离

## Codex

Codex 当前把 skills 做得更系统化，也更接近你能直接借鉴的架构。

它的核心特点：

- 基于 open agent skills standard
- skill 是目录，入口是 `SKILL.md`
- 支持 `scripts/`、`references/`、`assets/`
- 支持可选 `agents/openai.yaml`
- skills 在 CLI、IDE extension、app 中统一可用
- 显式激活和隐式激活并存
- 支持多层扫描：
  - repo
  - user
  - admin
  - system
- 支持配置层禁用 skill

Codex 有几个非常成熟的点：

### 1. Progressive disclosure 做得很明确

Codex 启动时只读 skill 的元数据：

- `name`
- `description`
- file path
- `agents/openai.yaml` 中的可选元数据

只有在模型决定要用 skill 时，才加载完整 `SKILL.md`。

### 2. Scope layering 很清晰

Codex 会从 repo、user、admin、system 多层位置读取 skill，这非常适合企业或团队环境。

### 3. Skill 可以声明依赖

`agents/openai.yaml` 可以配置：

- UI 元数据
- 是否允许隐式触发
- skill 依赖哪些工具，尤其是 MCP 工具

这点非常关键，因为它把“skill 描述”与“工具依赖声明”解耦了。

### 4. Skills 与 memory 分工清楚

从你当前环境内置的 skill 文档也能看出，Codex 把 skill 定义为：

- 专项工作流
- 领域知识
- 工具整合指南
- bunded resources 的分发单位

而不是持久 memory。

对你最有价值的地方：

- `openai.yaml` 这种 skill 元数据扩展层
- 多层 scope
- 安装、启停、内置 skill 的产品化思路

## deepagents

deepagents 的 skills 更偏 SDK 视角。

它的核心特点：

- 遵循 Agent Skills 规范
- skill 目录由调用方显式传入
- SDK 本身不自动扫描 `~/.agents/skills`
- 支持 source precedence，后传入者覆盖前者
- 支持给 subagent 配独立 skills
- skills 和 memory 明确分离

它很值得借鉴的不是“产品体验”，而是“架构边界”：

### 1. Skills 是可选输入，不是隐式魔法

在 deepagents 里，你创建 agent 时明确传：

- 哪些 skill 目录加载给主 agent
- 哪些 skill 目录加载给 subagent

这种设计利于可控性，也很适合你后面做多 agent。

### 2. Subagent skill 隔离

deepagents 明确指出：

- 主 agent 的 skill 不自动泄露给自定义 subagent
- subagent 需要自己声明 skill source

这对你的多 agent 研究方向很重要。未来你如果做：

- research agent
- coding agent
- report agent

就不该让所有 skill 默认共享。

### 3. “What the agent sees” 很清晰

deepagents 会在系统提示里注入一个 skills section，模型拿到一个最小 catalog，然后自行决定是否读取某个 skill 文件。

对你最有价值的地方：

- skill source 显式传入
- subagent skill 隔离
- 技能与 memory/tool 的职责边界非常清楚

## OpenHands

OpenHands 把 skills 和 plugins 分得很清楚，这一点非常适合你。

它的核心特点：

- 支持 `Skill(name, content, trigger)` 这种内存态 skill
- 也支持标准 `SKILL.md`
- 使用 `<available_skills>` 把 skill catalog 注入系统提示
- 支持 `KeywordTrigger`
- 支持 installed skill lifecycle
  - install
  - enable
  - disable
  - uninstall
- skills 遵循 progressive disclosure
- plugins 作为独立能力扩展层存在

最重要的两点：

### 1. Skills 与 plugins 分层

OpenHands 的方向非常明确：

- skill 是上下文和流程说明
- plugin 是代码能力扩展

这和你现在已经做好的工具系统天然吻合：

- `ToolService` 相当于 plugin/tool substrate
- 未来的 `SkillService` 负责给 agent 任务方法论

### 2. 技能管理生命周期比较完整

OpenHands 已经把 skills 当“可安装资源”在做：

- persistent storage
- enabled flag
- install / update / disable / uninstall

这说明 skill 体系如果要长期可用，最终都要走到“注册表 + 生命周期管理”，而不是单纯读本地文件。

对你最有价值的地方：

- `<available_skills>` catalog 形式
- skill 生命周期管理
- triggers 是可选增强，而不是强制标准字段

## OpenClaw

OpenClaw 的 skills 体系在工程落地上很成熟，尤其是“加载、过滤、快照、热更新”。

它的核心特点：

- 使用 AgentSkills 兼容目录
- skills 可来自：
  - bundled
  - managed/local
  - workspace
- workspace skill 覆盖 user skill，再覆盖 bundled skill
- skill 会在加载时按环境、配置、二进制存在性过滤
- 支持 watcher 自动刷新
- 会把可用 skill 以 compact XML 的形式注入系统提示
- 明确计算 skill list 的 token impact
- 插件可以自带 skills
- agent run 级别支持对 skill 注入 env/config

OpenClaw 很值得借鉴的点：

### 1. 先过滤，再暴露给模型

它不会把所有 skill 都展示给模型，而是先按配置、环境、可执行依赖做 eligibility filtering。

这是非常实用的工程经验：

- 不可用 skill 不要暴露给模型
- 否则模型会浪费 turn 去尝试激活不存在的能力

### 2. 会话快照

OpenClaw 会在 session 开始时快照当前可用 skill 集合，并在同会话内复用，必要时再热更新。

这对你未来接 skill 很重要，因为：

- 你不应该每轮都重新扫整个 skill tree
- 但又要支持开发期热更新

### 3. 明确关注 token cost

OpenClaw 甚至计算了 skill catalog 的字符和 token 开销。

这说明 skill 做多了以后，真正的问题不是“能不能读到”，而是“注入 catalog 的成本是不是可控”。

对你最有价值的地方：

- load-time filtering
- session snapshot
- hot reload watcher
- token-aware catalog 设计

---

## Shared Patterns Across Systems

综合上面这些系统，可以提炼出现在比较稳定的 industry pattern。

## 1. File-based skill package

主流系统基本都接受：

- 每个 skill 是一个目录
- 入口是 `SKILL.md`
- supporting resources 放在旁边

这样做的好处：

- 好分享
- 好安装
- 好做版本控制
- 好做覆盖和本地 patch

## 2. Progressive disclosure

这是最核心的共识。

启动时只加载：

- `name`
- `description`
- `location`
- 可选 UI metadata

真正触发时再加载：

- `SKILL.md` 正文
- skill 引用的脚本、参考文档、模板

这样可以显著降低 system prompt 常驻成本。

## 3. Description-driven matching

多数系统不做复杂规则引擎，而是：

- 让模型先看 skill 的 `description`
- 由模型决定要不要读 skill

因此 `description` 的质量直接决定 skill 触发质量。

## 4. Explicit + implicit activation

成熟系统一般同时支持：

- 显式激活
  - `/skill-name`
  - `$skill-name`
  - UI 点击
- 隐式激活
  - 模型依据 description 判断

这两者都很重要：

- 显式激活适合可控工作流
- 隐式激活适合自然语言交互

## 5. Skills are not tools

skills 负责组织能力，不直接替代工具系统。

典型工作方式是：

1. skill 被激活
2. skill 指导模型调用哪些工具
3. 模型再去调用文件、命令、搜索、浏览器、MCP 等工具

## 6. Scope layering and override

成熟系统都支持多层范围：

- system / bundled
- admin / org
- user
- repo / workspace

并且通常遵循：

- 越靠近工作区，优先级越高

这允许：

- 官方内置 skill
- 团队公共 skill
- 用户私有 skill
- 项目特定 skill

同时存在。

## 7. Skills need lifecycle management

一旦 skill 数量变多，就需要：

- install
- enable / disable
- override
- update
- remove

否则 skill 很快会失控。

## 8. Skills need security boundaries

技能本身是提示词载体，所以存在明显风险：

- 不可信仓库注入恶意 skill
- 让模型偏离正常任务
- 引导模型读取敏感文件
- 引导模型执行危险命令

因此实际系统都会做至少一部分：

- trusted workspace gating
- enable / disable
- load-time filtering
- 依赖声明
- approval / tool policy

---

## What Matters Most For BiliBrain

结合你当前系统，最重要的结论不是“照搬哪一家”，而是明确分层。

你现在已经有：

- `ToolService`
- `Workspace`
- `Policy`
- `Runtime`
- `LangChain @tool adapter`

所以你不应该把 skills 再做成另一套工具执行系统。

正确关系应该是：

```text
Agent
  -> Skill Catalog / Skill Activation
  -> Skill Instructions
  -> ToolService
       -> Filesystem Tools
       -> Command Runtime
       -> Future Browser/Search/Email/MCP Tools
```

也就是说：

- tools 是底层能力底座
- skills 是能力编排和上下文增强层

## 对你最适合的实现原则

### 1. Skill first, tool-aware

每个 skill 需要声明：

- 它解决什么问题
- 什么时候该触发
- 它假设有哪些工具可用

但不应该直接硬编码工具实现细节。

### 2. 采用 `SKILL.md` 目录格式

直接兼容主流格式，不要自己发明新 DSL。

建议目录结构：

```text
.agents/skills/
  web-research/
    SKILL.md
    references/
    scripts/
    assets/
    agents/
      bilibrain.yaml
```

其中：

- `SKILL.md` 走通用标准
- `agents/bilibrain.yaml` 走你自己的扩展元数据

### 3. 先做 dedicated activation tool

对你来说，比“让模型自己用读文件工具找 SKILL.md”更合适的是：

- 在 system prompt 注入 `available_skills`
- 提供 `activate_skill(name)` 工具

原因：

- 你能统一做权限和过滤
- 你能返回结构化 skill 内容
- 你能记录 analytics
- 你能保护 skill 内容不被误剪
- 以后可以做 skill dependencies 检查

### 4. 先只做 repo + user 两层

第一版别做太复杂。

建议先支持：

- repo: `<project>/.agents/skills`
- user: `~/.bilibrain/skills`
- system: `bilibrain/builtin_skills`

优先级：

`repo > user > system`

这已经足够覆盖你当前需求。

### 5. 只把“可用 skill 摘要”注入系统提示

不要把所有 `SKILL.md` 全注入。

建议 catalog 格式：

```xml
<available_skills>
  <skill>
    <name>web-research</name>
    <description>Use for open-web investigation, source comparison, and citation-heavy answers.</description>
    <location>repo:.agents/skills/web-research/SKILL.md</location>
  </skill>
</available_skills>
```

### 6. 激活后返回结构化 skill content

建议 `activate_skill` 返回：

- skill metadata
- normalized body
- resource list
- allowed tools / required tools
- scope

例如：

```xml
<skill_content name="web-research" scope="repo">
  <instructions>...</instructions>
  <skill_resources>
    <file>references/source-eval.md</file>
    <file>scripts/normalize_urls.py</file>
  </skill_resources>
</skill_content>
```

### 7. 技能内容要进入“受保护上下文”

如果你后面做对话压缩、会话记忆裁剪，skill 内容不能被普通历史摘要直接吞掉。

否则 agent 会出现：

- 前几轮会用 skill
- 几轮之后 silently forget
- 行为开始退化

这是很多系统都会专门处理的问题。

### 8. repo skills 必须有 trust 开关

这一点不要省。

建议规则：

- 默认加载 `system` 和 `user` skills
- `repo` skills 只有在 workspace trusted 时才加载

否则你以后一旦让 agent 支持外部仓库，就会有 prompt injection 风险。

---

## Recommended Architecture For BiliBrain

## Core Components

建议你下一阶段把 skills 层拆成这几个模块：

### 1. `SkillRegistry`

职责：

- 扫描 skill 目录
- 解析 `SKILL.md`
- 处理优先级覆盖
- 维护 enabled / disabled 状态
- 产出 `available_skills`

### 2. `SkillLoader`

职责：

- 加载 skill 正文
- 解析 supporting resources
- 产出结构化 activation payload

### 3. `SkillPolicy`

职责：

- 判断某个 scope 是否允许
- repo skill 是否可信
- skill 所声明的依赖是否满足
- skill 是否允许隐式触发

### 4. `SkillService`

职责：

- `list_skills(session_id, workspace_id)`
- `activate_skill(name, session_id, workspace_id)`
- activation 去重
- activation 审计记录

### 5. `SkillPromptFormatter`

职责：

- 把 `available_skills` 格式化成 prompt section
- 把激活结果格式化成结构化内容

### 6. `SkillState`

职责：

- 当前 session 已激活哪些 skill
- 是否已经注入
- 是否需要重新加载
- 供上下文压缩器识别保护

## Suggested Metadata

第一版你可以只支持这些字段：

`SKILL.md` frontmatter:

- `name` required
- `description` required
- `disable-model-invocation` optional
- `allowed-tools` optional
- `requires` optional
- `metadata` optional

`agents/bilibrain.yaml`:

- `interface.display_name`
- `interface.short_description`
- `policy.allow_implicit_invocation`
- `dependencies.tools`
- `dependencies.skills`

这样既兼容主流格式，又保留你自己的扩展空间。

## Activation Model

对你这套系统，我建议分两阶段。

### Phase 1

- UI / API 可列出 skills
- agent 获得 `available_skills`
- agent 通过 `activate_skill(name)` 激活
- skill 激活后进入当前会话状态
- 由 agent 自己继续调用 tools

### Phase 2

- 支持显式 `/skill-name`
- 支持 user skill enable / disable
- 支持 skill dependencies 校验
- 支持 subagent 专属 skill 集
- 支持技能市场或远程 skill 安装

---

## Initial Skill Categories For BiliBrain

你这个系统最适合先做的不是“通用技能市场”，而是几个强场景 skill。

## 1. `web-research`

用途：

- 开放网页检索
- 多来源对比
- 引用整理
- 事实核验

依赖工具：

- `search_web`
- `fetch_url`
- `agent-browser` 或未来浏览器工具

## 2. `workspace-coding`

用途：

- 读写文件
- grep / glob
- run command
- 修改代码后做验证

依赖工具：

- `list_dir`
- `read_file`
- `write_file`
- `append_file`
- `run_command`

## 3. `video-knowledge-analysis`

用途：

- 针对 BiliBrain 现有视频知识库做总结、提取、归纳
- 指导 agent 什么时候用 summary-first，什么时候走 chunk retrieval

依赖工具：

- 你现有的 RAG/summary/query tools

## 4. `report-writing`

用途：

- 输出研究报告、技术说明、周报
- 规范结构和引用方式

依赖工具：

- 文件工具
- 搜索工具
- 未来邮件/导出工具

---

## Key Design Decisions

## Decision 1: Skills should be instruction packages, not executable plugins

原因：

- 这和现有主流方案一致
- 能直接复用你已经完成的工具系统
- 风险更低，边界更清晰

## Decision 2: Use the open `SKILL.md` directory format

原因：

- 兼容 Claude Code / Codex / deepagents / OpenHands / OpenClaw 的共同模式
- 以后可复用公开 skill 资源
- 不把自己锁死在私有格式里

## Decision 3: Prefer `activate_skill` over raw file-reading activation

原因：

- 更容易做策略控制
- 更容易做上下文保护
- 更容易做分析和日志
- 更适合你已有的后端服务形态

## Decision 4: Separate skills from tools and memory

原因：

- 工程复杂度更低
- 模型行为更稳定
- 更符合未来多 agent 扩展

---

## Risks And Guardrails

## 1. Prompt injection via repo skills

风险：

- 外部仓库可通过 skill 注入恶意指令

措施：

- repo skills 只在 trusted workspace 下启用
- 默认先只启 system + user

## 2. Skill catalog bloat

风险：

- skill 过多时，系统提示变重

措施：

- 只注入摘要
- 做 scope filtering
- 后面可按 feature / workspace / mode 筛选

## 3. Skill duplication and conflict

风险：

- 多个 skill 内容相似或冲突

措施：

- 明确优先级
- activation 去重
- skill description 要写清边界

## 4. Tool dependency mismatch

风险：

- skill 被激活，但依赖工具未启用

措施：

- `activate_skill` 阶段做依赖检查
- 不可用 skill 直接从 catalog 隐藏或标为 disabled

---

## Recommended Next Steps

按你当前系统状态，建议顺序是：

1. 实现 `SkillRegistry`
2. 实现 `activate_skill`
3. 为会话注入 `available_skills`
4. 做 session 级 skill state
5. 做 repo trust gating
6. 先写 2 到 4 个高质量内置 skill

我建议第一版不要做：

- 远程安装市场
- 自动关键词触发
- 复杂 UI 管理
- 技能依赖求解器

先把最核心的“发现 -> 激活 -> 注入 -> 保持”链路跑通。

---

## References

- Agent Skills 规范总览: https://agentskills.io/what-are-skills
- Agent Skills 客户端实现指南: https://agentskills.io/client-implementation/adding-skills-support
- Claude Code Skills 文档: https://code.claude.com/docs/en/skills
- Codex Skills 文档: https://developers.openai.com/codex/skills
- deepagents Skills 文档: https://docs.langchain.com/oss/python/deepagents/skills
- OpenHands Skills 文档: https://docs.openhands.dev/sdk/guides/skill
- OpenHands Plugins 文档: https://docs.openhands.dev/sdk/guides/plugins
- OpenClaw Skills 文档: https://docs.openclaw.ai/tools/skills
- 当前环境内置 Codex skill 说明:
  - [skill-creator](C:/Users/26961/.codex/skills/.system/skill-creator/SKILL.md)
  - [skill-installer](C:/Users/26961/.codex/skills/.system/skill-installer/SKILL.md)

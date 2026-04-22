---
name: video-summary-to-obsidian
description: 当用户要求把视频总结、摘要或笔记保存到 Obsidian、导出到本地知识库、写入 Vault 时使用。典型触发词包括：把这个视频总结保存到 Obsidian、帮我存成笔记、导出到知识库、记录这期视频、存到 Vault。本 skill 会先完成视频内容整理，再调用 obsidian-cli 写入本地。如果用户只是要求总结视频但没有提到保存，使用 video-summary-writer 而不是本 skill。
allowed-tools: [search_video_summaries, search_knowledge_base, obsidian_write_note, obsidian_read_note]
metadata:
  short-description: 视频总结并保存到 Obsidian
  when-to-use: 用户需要把单个视频整理为完整笔记并写入 Obsidian Vault。
  input-hint: 优先拿到视频标题、BV号或链接；如果用户指定文件名或 Vault，以用户要求为准。
---

# video-summary-to-obsidian

你是 BiliBrain 的“视频总结 + 保存”skill，负责先把单个视频整理成高密度的完整内容还原文档，再通过 obsidian-cli 写入本地 Obsidian Vault。

## 执行流程

严格按顺序执行，不得跳步。

### 阶段一：内容整理

1. 调用 `search_video_summaries`，获取视频摘要、主题框架和核心话题列表。
2. 针对摘要中的每个核心话题，反复多次调用 `search_knowledge_base`，直到该话题有足够 chunk 内容支撑 300～600 字展开。
3. 在内部组装完整 Markdown 文档，不向用户提前输出正文。

检索规则：
- 每次检索带具体问题，不泛泛检索。
- 同一话题从“是什么”“为什么”“怎么做”“有什么例子”“有什么注意事项”多个角度分别检索。
- 如果某话题检索结果确实不足，在文档中如实注明，不用常识补全。

### 阶段二：写入 Obsidian

4. 确定文件名与 vault-relative path。
5. 直接调用 `obsidian_write_note` 保存完整 Markdown。
6. 如需额外确认，再调用 `obsidian_read_note` 读取同一路径做补充校验。
7. 基于真实返回结果向用户汇报成功或失败。

## 文档结构

组装的 Markdown 必须按以下结构输出。文件开头必须是标准 YAML frontmatter，不得省略首尾 `---`。

```markdown
---
title: {{视频标题}}
source: {{视频 URL 或 BV 号，有则填}}
source_url: {{完整视频链接；若只有 BV 号，则写成 https://www.bilibili.com/video/{{BV号}}}}
date: {{今日日期，格式 YYYY-MM-DD}}
tags: [bilibili, 视频笔记]
---

## 视频主旨
3～5 句话说清这支视频讲了什么、面向谁、核心主张是什么、作者想解决什么问题。

## 详细内容

### {{话题一标题}}

完整还原这个话题下视频讲的所有内容：背景、论点、论据、示例、结论。
有步骤写步骤，有对比写对比，有数据保留数据，有代码/命令原样列出。

### {{话题二标题}}

同上。话题数量跟着视频走，不限制上限。

---

## 金句 / 关键定义
视频中值得记录的原话、定义、类比。能引用原文就引用原文。

## 实用速查
仅在视频确实包含以下内容时输出对应小节，否则整节跳过：

### 操作步骤 / 命令
### 常见误区与正确做法
### 推荐工具 / 资源

## 一句话回顾
适合收藏或复习的一句话，点出最核心的收获。
```

## 标题与文件名规则

- `title` 属性和 `name=` 文件名默认使用同一个主标题，除非用户显式指定文件名。
- 保留英文产品名内部空格，例如 `Claude Code`、`OpenAI Agents SDK`。
- 文件名不要包含 `#`。
- 在最终 vault-relative path 中应显式加 `.md`，但若遗漏，`obsidian_write_note` 也会自动补上。
- 当前系统运行在 Windows；标题中若含有 `< > : " / \ | ? *`，只移除这些非法字符，不改动其他文字。
- 优先使用 `path=` 精确路径，不使用 `name=` / `file=` 做模糊解析。

## Obsidian 写入规则

必须遵守以下规则：

- 不要再用 `run_command` 手拼 `obsidian create content=...` 保存完整笔记。
- 统一使用 `obsidian_write_note`；它内部会完成 vault 定位、文件写入和 Obsidian 侧校验。
- `obsidian_write_note.path` 使用 vault-relative path，例如 `BiliBrain/Claude Code的设计哲学：渐进式披露.md`。
- `obsidian_write_note.content` 必须直接传完整 Markdown 文档。

推荐调用方式：

```json
{
  "path": "BiliBrain/Claude Code的设计哲学：渐进式披露.md",
  "content": "---\ntitle: Claude Code的设计哲学：渐进式披露\nsource: BV14QPvzuEUR\nsource_url: https://www.bilibili.com/video/BV14QPvzuEUR\ndate: 2026-01-04\ntags: [bilibili, 视频笔记]\n---\n\n## 视频主旨\n...",
  "overwrite": true
}
```

读回校验方式：

```json
{
  "path": "BiliBrain/Claude Code的设计哲学：渐进式披露.md"
}
```

## 成功判定

只有同时满足以下条件，才算真正成功：

- `obsidian_write_note` 返回成功。
- 返回 payload 中 `verified = true`。
- 读回内容中能看到 `## 视频主旨`，并且正文明显不只是标题或 frontmatter。

如果读回结果只包含标题、仅包含 frontmatter、或缺少 `## 视频主旨`，说明保存并不完整，必须视为失败，不能向用户宣称“已成功保存”。

## 失败处理

- 只在阶段三内部处理，不得回到检索或重写阶段。
- 先检查真实 `stdout` / `stderr`。
- 如果保存失败、验证失败、只写入标题或文件不存在，不得退回使用 `run_command` 手拼 Obsidian CLI 参数。
- 必须继续停留在 `obsidian_write_note` / `obsidian_read_note` 这套专用工具链里处理问题。
- 若重试后仍失败，只能基于真实返回结果说明失败，并把完整 Markdown 正文直接输出给用户作为备选。

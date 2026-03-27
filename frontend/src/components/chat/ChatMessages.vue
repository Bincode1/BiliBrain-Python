<template>
  <div :ref="store.setChatStreamEl" class="chat-stream">
    <div v-if="chatHistoryLoading" class="empty-state chat-empty">
      正在加载历史对话...
    </div>
    <template v-else-if="chatMessages.length">
      <article v-for="(message, index) in chatMessages" :key="message.message_id || index" class="message" :class="message.role">
        <div class="message-head">
          <div class="message-role">{{ message.role === "user" ? "你" : "BiliBrain" }}</div>
          <span
            v-if="message.role === 'assistant' && message.route_mode"
            class="message-mode-badge route-badge"
            :class="message.route_mode"
          >
            {{ messageRouteLabel(message) }}
          </span>
          <span
            v-if="message.role === 'assistant' && message.answer_mode"
            class="message-mode-badge"
            :class="message.answer_mode"
          >
            {{ messageModeLabel(message) }}
          </span>
        </div>
        <div class="message-body" v-html="renderMessageBody(message)"></div>
        <div
          v-if="message.role === 'assistant' && (message.agent_status || message.research_plan || message.agent_events?.length || message.active_skills?.length || message.skill_events?.length || message.tool_events?.length)"
          class="agent-activity-panel"
        >
          <div v-if="message.agent_status" class="agent-status-line">
            <span class="agent-status-dot"></span>
            <span>{{ message.agent_status }}</span>
          </div>

          <div v-if="message.research_plan?.task_count" class="agent-activity-block">
            <div class="agent-activity-label">研究子任务</div>
            <div class="agent-activity-list">
              <div v-for="task in message.research_plan.tasks || []" :key="task.task_id || task.title" class="agent-activity-item">
                <span class="agent-activity-kind research-kind">任务</span>
                <span>{{ task.title }}<template v-if="task.objective">：{{ task.objective }}</template></span>
              </div>
            </div>
          </div>

          <div v-if="message.agent_events?.length" class="agent-activity-block">
            <div class="agent-activity-label">研究进度</div>
            <div class="agent-activity-list">
              <div v-for="item in message.agent_events" :key="item._id" class="agent-activity-item">
                <span class="agent-activity-kind research-kind">{{ formatAgentEventPhase(item) }}</span>
                <span>{{ formatAgentEvent(item) }}</span>
              </div>
            </div>
          </div>

          <div v-if="message.active_skills?.length" class="agent-activity-block">
            <div class="agent-activity-label">当前 Skills</div>
            <div class="agent-chip-row">
              <span v-for="skill in message.active_skills" :key="`active-${skill.name}`" class="agent-chip skill-chip">
                {{ skill.name }}
              </span>
            </div>
          </div>

          <div v-if="message.skill_events?.length" class="agent-activity-block">
            <div class="agent-activity-label">Skills 动态</div>
            <div class="agent-activity-list">
              <div v-for="item in message.skill_events" :key="item._id" class="agent-activity-item">
                <span class="agent-activity-kind skill-kind">{{ item.phase === "activated" ? "已激活" : "处理中" }}</span>
                <span>{{ item.message || item.name }}</span>
              </div>
            </div>
          </div>

          <div v-if="message.tool_events?.length" class="agent-activity-block">
            <div class="agent-activity-label">工具步骤</div>
            <div class="agent-activity-list">
              <div v-for="item in message.tool_events" :key="item._id" class="agent-activity-item">
                <span class="agent-activity-kind tool-kind">{{ item.phase === "finish" ? (item.ok ? "完成" : "失败") : "调用中" }}</span>
                <span>{{ formatToolEvent(item) }}</span>
              </div>
            </div>
          </div>
        </div>
        <div v-if="message.sources?.length" class="source-panel">
          <div class="source-summary">
            <div class="source-summary-copy">
              <div class="source-summary-head">
                <div class="source-label">{{ messageSourceLabel(message) }}</div>
                <button class="ghost-button small source-toggle-button" type="button" @click="store.toggleMessageSources(message)">
                  {{ message.sourcesExpanded ? "收起来源" : `展开 ${message.sources.length} 条来源` }}
                </button>
              </div>
              <div v-if="!message.sourcesExpanded" class="source-chip-row">
                <a
                  v-for="source in message.sources.slice(0, 3)"
                  :key="`compact-${source.ref_index}`"
                  :href="source.jump_url"
                  target="_blank"
                  rel="noreferrer"
                  class="source-chip"
                >
                  <span class="source-ref-mini">资料 {{ source.ref_index }}</span>
                  <strong>{{ sourcePreviewTitle(source) }}</strong>
                  <span>{{ source.timestamp }}</span>
                </a>
                <span v-if="message.sources.length > 3" class="source-chip muted-more">
                  还有 {{ message.sources.length - 3 }} 条
                </span>
              </div>
              <div v-else class="source-list">
                <a
                  v-for="(source, sourceIndex) in message.sources"
                  :key="sourceIndex"
                  :href="source.jump_url"
                  target="_blank"
                  rel="noreferrer"
                  class="source-item"
                >
                  <span class="source-ref">资料 {{ source.ref_index }}</span>
                  <div class="source-copy">
                    <strong>{{ source.video_title || source.title || source.url || "未命名来源" }}</strong>
                    <span>{{ sourceMetaLabel(source) }}</span>
                  </div>
                </a>
              </div>
            </div>
          </div>
        </div>
      </article>
    </template>
    <div v-else class="empty-state chat-empty">
      <div class="chat-empty-card">
        <span class="chat-empty-kicker">{{ chatConversations.length ? "开始对话" : "新会话" }}</span>
        <strong>{{ chatConversations.length ? "这条会话还没有消息" : "直接输入你的第一个问题" }}</strong>
        <p>{{ chatConversations.length ? "可以直接继续问，也可以切到底部选择收藏夹范围。" : "系统会自动创建会话并按你选择的范围检索内容。" }}</p>
        <div class="chat-empty-suggestions">
          <span>总结这个收藏夹重点</span>
          <span>找出某个主题的视频</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { marked } from "marked";
import { storeToRefs } from "pinia";

import { useWorkspaceStore } from "@/stores/workspace";
import {
  messageModeLabel,
  messageRouteLabel,
  messageSourceLabel,
  sourceMetaLabel,
  sourcePreviewTitle,
} from "@/utils/chat";

const store = useWorkspaceStore();
const { chatConversations, chatHistoryLoading, chatMessages } = storeToRefs(store);

function renderMessageBody(message) {
  const text = message.text || "";
  const sources = message.sources || [];

  const sourceMap = new Map(
    sources
      .map((s) => [Number(s.ref_index), s])
      .filter(([idx]) => Number.isFinite(idx) && idx > 0)
  );

  let html = marked.parse(text);

  if (sourceMap.size > 0) {
    html = html.replace(/【(\d+)】/g, (_, rawIndex) => {
      const idx = Number(rawIndex);
      const source = sourceMap.get(idx);
      if (source?.jump_url) {
        const titleBase = source.title || source.video_title || "资料";
        const title = `${titleBase} ${source.timestamp ? `· ${source.timestamp}` : ""}`;
        const escapedUrl = source.jump_url
          .replaceAll("&", "&amp;")
          .replaceAll("<", "&lt;")
          .replaceAll(">", "&gt;")
          .replaceAll('"', "&quot;");
        return `<a class="inline-citation" href="${escapedUrl}" target="_blank" rel="noreferrer" title="${title}">资料 ${idx}</a>`;
      }
      return `【${rawIndex}】`;
    });
  }

  return html;
}

function formatToolEvent(item) {
  const summary = item?.summary || {};
  if (item?.name === "run_command") {
    return `run_command: ${summary.command || ""}`.trim();
  }
  if (item?.name === "write_file" || item?.name === "append_file") {
    return `${item.name}: ${summary.path || ""}`.trim();
  }
  if (item?.name === "make_dir") {
    return `make_dir: ${summary.path || ""}`.trim();
  }
  if (item?.name === "read_file" || item?.name === "list_dir") {
    return `${item.name}: ${summary.path || "."}`.trim();
  }
  return item?.name || "tool";
}

function formatAgentEventPhase(item) {
  if (item?.status === "completed") {
    return "完成";
  }
  if (item?.status === "running") {
    return "进行中";
  }
  return "更新";
}

function formatAgentEvent(item) {
  const agent = item?.agent || "agent";
  const message = item?.message || "";
  const completed = Number(item?.completed || 0);
  const total = Number(item?.total || 0);
  const progress = total > 0 ? ` (${completed}/${total})` : "";
  return `${agent}${progress}${message ? `：${message}` : ""}`;
}
</script>

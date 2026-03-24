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
        <div class="message-body" v-html="renderMarkdown(message.text, message.sources)"></div>
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
                    <strong>{{ source.video_title }}</strong>
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
      {{ chatConversations.length ? "当前会话还没有消息，直接开始提问即可。" : "先新建一个会话，或者直接提问自动创建会话。" }}
    </div>
  </div>
</template>

<script setup>
import { storeToRefs } from "pinia";

import { useWorkspaceStore } from "@/stores/workspace";
import {
  messageModeLabel,
  messageRouteLabel,
  messageSourceLabel,
  renderMarkdown,
  sourceMetaLabel,
  sourcePreviewTitle,
} from "@/utils/chat";

const store = useWorkspaceStore();
const { chatConversations, chatHistoryLoading, chatMessages } = storeToRefs(store);
</script>

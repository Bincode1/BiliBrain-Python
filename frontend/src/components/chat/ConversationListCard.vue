<template>
  <section class="side-card conversation-side-card">
    <div class="side-card-head">
      <div>
        <div class="side-card-label">对话</div>
        <h3>会话列表</h3>
      </div>
      <button class="ghost-button small" type="button" @click="store.createConversation">新建</button>
    </div>
    <div class="conversation-side-list">
      <div v-if="chatConversationsLoading" class="conversation-popover-empty">正在读取会话...</div>
      <div v-else-if="!chatConversations.length" class="conversation-popover-empty">还没有会话。</div>
      <div v-else class="conversation-popover-list">
        <article
          v-for="(conversation, index) in chatConversations"
          :key="conversation.conversation_id"
          class="conversation-popover-item"
          :class="{ active: Number(activeConversationId) === Number(conversation.conversation_id) }"
        >
          <button
            class="conversation-main"
            :disabled="chatConversationsLoading && Number(activeConversationId) === Number(conversation.conversation_id)"
            type="button"
            :title="conversationLabel(conversation, index)"
            @click="store.selectConversation(conversation.conversation_id)"
          >
            <span class="conversation-title">{{ conversationShortLabel(conversation, index) }}</span>
          </button>
          <button
            class="conversation-delete"
            type="button"
            :disabled="Number(deletingConversationId) === Number(conversation.conversation_id)"
            title="删除会话"
            @click="store.deleteConversation(conversation.conversation_id)"
          >
            ×
          </button>
        </article>
      </div>
    </div>
  </section>
</template>

<script setup>
import { storeToRefs } from "pinia";

import { useWorkspaceStore } from "@/stores/workspace";
import { conversationLabel, conversationShortLabel } from "@/utils/chat";

const store = useWorkspaceStore();
const { activeConversationId, chatConversations, chatConversationsLoading, deletingConversationId } = storeToRefs(store);
</script>

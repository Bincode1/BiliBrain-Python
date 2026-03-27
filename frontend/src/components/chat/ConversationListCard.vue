<template>
  <section class="side-card conversation-side-card">
    <div class="side-card-head">
      <div>
        <div class="side-card-label">对话</div>
      </div>
      <button class="ghost-button small" type="button" @click="store.createConversation">新会话</button>
    </div>
    <div class="conversation-side-list">
      <div v-if="chatConversationsLoading" class="conversation-popover-empty">正在读取会话...</div>
      <div v-else-if="!chatConversations.length" class="conversation-popover-empty conversation-empty-card">
        <strong>还没有会话</strong>
        <p>直接发送第一条消息就会自动创建。</p>
      </div>
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
            @click="handleSelect(conversation.conversation_id)"
          >
            <span class="conversation-title">{{ conversationShortLabel(conversation, index) }}</span>
            <span class="conversation-meta">{{ conversation.message_count }} 条消息</span>
          </button>
          <button
            class="conversation-actions-trigger"
            type="button"
            :disabled="
              Number(deletingConversationId) === Number(conversation.conversation_id) ||
              Number(renamingConversationId) === Number(conversation.conversation_id)
            "
            title="更多操作"
            @click.stop="toggleMenu(conversation.conversation_id)"
          >
            ⋯
          </button>
          <div
            v-if="Number(openMenuId) === Number(conversation.conversation_id)"
            class="conversation-actions-menu"
          >
            <button
              class="conversation-actions-item"
              type="button"
              :disabled="Number(renamingConversationId) === Number(conversation.conversation_id)"
              @click="handleRename(conversation.conversation_id)"
            >
              重命名
            </button>
            <button
              class="conversation-actions-item danger"
              type="button"
              :disabled="Number(deletingConversationId) === Number(conversation.conversation_id)"
              @click="handleDelete(conversation.conversation_id)"
            >
              删除
            </button>
          </div>
        </article>
      </div>
    </div>
  </section>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref } from "vue";
import { storeToRefs } from "pinia";

import { useWorkspaceStore } from "@/stores/workspace";
import { conversationLabel, conversationShortLabel } from "@/utils/chat";

const store = useWorkspaceStore();
const openMenuId = ref(null);
const { activeConversationId, chatConversations, chatConversationsLoading, deletingConversationId, renamingConversationId } =
  storeToRefs(store);

function toggleMenu(conversationId) {
  openMenuId.value = Number(openMenuId.value) === Number(conversationId) ? null : Number(conversationId);
}

async function handleRename(conversationId) {
  openMenuId.value = null;
  await store.renameConversation(conversationId);
}

async function handleDelete(conversationId) {
  openMenuId.value = null;
  await store.deleteConversation(conversationId);
}

async function handleSelect(conversationId) {
  openMenuId.value = null;
  await store.selectConversation(conversationId);
}

function handleDocumentClick(event) {
  const target = event.target;
  if (!(target instanceof HTMLElement)) {
    openMenuId.value = null;
    return;
  }
  if (target.closest(".conversation-popover-item")) {
    return;
  }
  openMenuId.value = null;
}

onMounted(() => {
  document.addEventListener("click", handleDocumentClick);
});

onBeforeUnmount(() => {
  document.removeEventListener("click", handleDocumentClick);
});
</script>

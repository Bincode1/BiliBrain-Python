<template>
  <section class="panel chat-panel">
    <div class="chat-layout">
      <div class="chat-main-column">
        <div class="chat-reading-head">
          <div class="chat-reading-label">当前会话</div>
          <div class="chat-reading-title" :title="selectedConversation ? conversationLabel(selectedConversation) : '未选择会话'">
            {{ selectedConversation ? conversationLabel(selectedConversation) : "未选择会话" }}
          </div>
        </div>

        <div :class="statusClass(chatStatus)">{{ chatStatus.message }}</div>

        <ChatMessages />
        <ChatComposer />
      </div>

      <aside class="chat-side-column">
        <CurrentVideoCard />
        <ConversationListCard />
      </aside>
    </div>
  </section>
</template>

<script setup>
import { storeToRefs } from "pinia";

import { statusClass } from "@/composables/useStatus";
import ChatComposer from "@/components/chat/ChatComposer.vue";
import ChatMessages from "@/components/chat/ChatMessages.vue";
import ConversationListCard from "@/components/chat/ConversationListCard.vue";
import CurrentVideoCard from "@/components/video/CurrentVideoCard.vue";
import { useWorkspaceStore } from "@/stores/workspace";
import { conversationLabel } from "@/utils/chat";

const store = useWorkspaceStore();
const { chatStatus, selectedConversation } = storeToRefs(store);
</script>

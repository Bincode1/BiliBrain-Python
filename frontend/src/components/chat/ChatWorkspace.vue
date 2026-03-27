<template>
  <section class="panel chat-panel">
    <div class="chat-layout">
      <div class="chat-main-column">
        <SkillApprovalBar />

        <div :class="statusClass(chatStatus)">{{ chatStatus.message }}</div>

        <ChatMessages />
        <ChatComposer :folder-only="folderOnly" />
      </div>

      <aside class="chat-side-column">
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
import SkillApprovalBar from "@/components/chat/SkillApprovalBar.vue";
import { useWorkspaceStore } from "@/stores/workspace";

defineProps({
  folderOnly: {
    type: Boolean,
    default: false,
  },
});

const store = useWorkspaceStore();
const { chatStatus } = storeToRefs(store);
</script>

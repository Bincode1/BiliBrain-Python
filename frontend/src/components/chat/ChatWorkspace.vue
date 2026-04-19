<template>
  <section class="grid h-full grid-rows-[1fr_auto]">
    <!-- Messages area (scrollable, fills remaining space) -->
    <div class="min-h-0 flex flex-col overflow-hidden flex-1">
      <ChatMessages />

      <div v-if="chatStatus.show" :class="['mx-auto max-w-4xl shrink-0 rounded-md px-3 py-1 text-[12px]', chatStatus.error ? 'bg-destructive/10 text-destructive' : 'bg-muted text-muted-foreground']">
        {{ chatStatus.message }}
      </div>
    </div>

    <!-- Composer (always pinned at bottom) -->
    <div class="flex justify-center px-3 pb-3 pt-1.5">
      <div class="w-full max-w-4xl">
        <ChatComposer :folder-only="folderOnly" />
      </div>
    </div>
  </section>
</template>

<script setup>
import { storeToRefs } from "pinia";

import ChatComposer from "@/components/chat/ChatComposer.vue";
import ChatMessages from "@/components/chat/ChatMessages.vue";
import { useChatStore } from "@/stores/chat";

defineProps({
  folderOnly: { type: Boolean, default: false },
});

const store = useChatStore();
const { chatStatus } = storeToRefs(store);
</script>

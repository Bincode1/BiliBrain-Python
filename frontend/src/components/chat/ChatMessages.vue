<template>
  <!-- Loading state -->
  <div v-if="chatHistoryLoading" class="flex flex-1 items-center justify-center text-sm text-muted-foreground">
    正在加载历史对话...
  </div>

  <!-- Conversation mode (≤100 messages): uses StickToBottom for auto-scroll -->
  <Conversation v-else-if="chatMessages.length && !useVirtualMode" class="min-h-0 flex-1">
    <ConversationContent class="gap-4 max-w-[720px] mx-auto px-4">
      <ChatMessageItem
        v-for="(message, index) in chatMessages"
        :key="message.message_id || index"
        :message="message"
        @toggle-sources="store.toggleMessageSources"
      />
      <SkillApprovalBar />
    </ConversationContent>
    <ConversationScrollButton />
  </Conversation>

  <!-- Virtual scroll mode (>100 messages): keeps existing smart/virtual scroll -->
  <div
    v-else-if="chatMessages.length && useVirtualMode"
    :ref="setContainerRef"
    class="min-h-0 flex-1 flex-col gap-4 overflow-y-auto scrollbar-gutter-stable"
  >
    <div class="max-w-[720px] mx-auto px-4">
      <div :style="spacerTopStyle" />
      <ChatMessageItem
        v-for="message in visibleMessages"
        :key="message.message_id || message._vtIndex"
        :message="message"
        :data-vt-index="message._vtIndex"
        @toggle-sources="store.toggleMessageSources"
      />
      <SkillApprovalBar />
      <div :style="spacerBottomStyle" />
    </div>
  </div>

  <!-- Empty state -->
  <ConversationEmptyState v-else class="max-w-[720px] mx-auto px-4">
    <div class="flex flex-col items-center gap-3 rounded-xl border border-dashed border-border px-8 py-10 text-center">
      <span class="text-[10px] uppercase tracking-widest text-muted-foreground">
        {{ chatConversations.length ? "开始对话" : "新会话" }}
      </span>
      <strong class="text-sm">{{ chatConversations.length ? "这条会话还没有消息" : "直接输入你的第一个问题" }}</strong>
      <p class="text-xs text-muted-foreground">
        {{ chatConversations.length ? "可以直接继续问，也可以切到底部选择收藏夹范围。" : "系统会自动创建会话并按你选择的范围检索内容。" }}
      </p>
      <div class="flex flex-wrap gap-2">
        <span class="rounded-full bg-muted px-3 py-1 text-[11px] text-muted-foreground">总结这个收藏夹重点</span>
        <span class="rounded-full bg-muted px-3 py-1 text-[11px] text-muted-foreground">找出某个主题的视频</span>
      </div>
    </div>
  </ConversationEmptyState>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";

import { useChatStore } from "@/stores/chat";
import { useSmartScroll } from "@/composables/useSmartScroll";
import { useVirtualScroll } from "@/composables/useVirtualScroll";
import {
  Conversation,
  ConversationContent,
  ConversationScrollButton,
  ConversationEmptyState,
} from "@/components/ai-elements/conversation";
import ChatMessageItem from "./ChatMessageItem.vue";
import SkillApprovalBar from "./SkillApprovalBar.vue";

const VIRTUAL_SCROLL_THRESHOLD = 100;

const store = useChatStore();
const { chatConversations, chatHistoryLoading, chatMessages } = storeToRefs(store);

const useVirtualMode = computed(() => chatMessages.value.length > VIRTUAL_SCROLL_THRESHOLD);

// Virtual scroll setup (only used when >100 messages)
const containerRef = ref(null);
const smartScroll = useSmartScroll(containerRef);
const virtualScroll = useVirtualScroll({ items: chatMessages, containerRef });
const { visibleMessages, spacerTopStyle, spacerBottomStyle } = virtualScroll;

// Agent status cleanup
watch(chatMessages, (messages) => {
  for (const msg of messages) {
    if (msg.role !== "assistant" || msg._streaming) continue;
    if (msg.agent_status) msg.agent_status = "";
  }
}, { flush: "sync" });

// Virtual scroll initialization
let virtualScrollInitialized = false;

function setContainerRef(el) {
  containerRef.value = el;
  store.setChatStreamEl(el);
  if (el) {
    store.registerSmartScrollHandle(smartScroll);
    smartScroll.bind();
    if (useVirtualMode.value && !virtualScrollInitialized) {
      virtualScroll.init();
      virtualScrollInitialized = true;
    }
  }
}

watch(useVirtualMode, (enabled) => {
  if (enabled && containerRef.value && !virtualScrollInitialized) {
    store.registerSmartScrollHandle(smartScroll);
    virtualScroll.init();
    virtualScrollInitialized = true;
  }
});

onMounted(() => {
  if (useVirtualMode.value && containerRef.value) {
    store.registerSmartScrollHandle(smartScroll);
    virtualScroll.init();
    virtualScrollInitialized = true;
  }
});

onUnmounted(() => {
  smartScroll.dispose();
  if (virtualScrollInitialized) virtualScroll.dispose();
});
</script>

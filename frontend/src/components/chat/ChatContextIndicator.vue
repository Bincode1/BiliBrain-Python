<template>
  <Context v-if="limitTokens > 0" v-bind="contextProps">
    <ContextTrigger />
    <ContextContent>
      <ContextContentHeader />
    </ContextContent>
  </Context>
</template>

<script setup>
import { computed } from "vue";
import { storeToRefs } from "pinia";

import {
  Context,
  ContextContent,
  ContextContentHeader,
  ContextTrigger,
} from "@/components/ai-elements/context";
import { useChatStore } from "@/stores/chat";

const store = useChatStore();
const { chatContextUsage } = storeToRefs(store);

const currentTokens = computed(() => Number(chatContextUsage.value.currentTokens || 0));
const limitTokens = computed(() => Number(chatContextUsage.value.limitTokens || 0));
const contextProps = computed(() => ({
  usedTokens: currentTokens.value,
  maxTokens: limitTokens.value,
  modelId: "openai:gpt-5",
  usage: {
    inputTokens: currentTokens.value,
    outputTokens: 0,
    totalTokens: currentTokens.value,
    cachedInputTokens: 0,
    reasoningTokens: 0,
  },
}));
</script>

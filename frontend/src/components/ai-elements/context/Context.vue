<script setup lang="ts">
import { HoverCard } from "@/components/ui/hover-card"
import { provideContextState } from "./context"

const props = defineProps<{
  usedTokens: number
  maxTokens: number
  modelId?: string
  usage?: {
    inputTokens?: number
    outputTokens?: number
    totalTokens?: number
    cachedInputTokens?: number
    reasoningTokens?: number
  }
}>()

provideContextState(props)
</script>

<template>
  <HoverCard :open-delay="0" :close-delay="0">
    <slot />
  </HoverCard>
</template>

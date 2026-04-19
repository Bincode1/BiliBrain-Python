<script setup lang="ts">
import { computed } from "vue"
import { useContextState } from "./context"

const { props, percent } = useContextState()

const formattedUsed = computed(() => Number(props.usedTokens || 0).toLocaleString("zh-CN"))
const formattedMax = computed(() => Number(props.maxTokens || 0).toLocaleString("zh-CN"))
</script>

<template>
  <div class="space-y-3 px-4 py-4">
    <div class="flex items-center justify-between text-[14px] leading-5">
      <span class="font-medium text-foreground">{{ percent.toFixed(1) }}%</span>
      <span class="text-muted-foreground">
        {{ formattedUsed }} <span class="px-1">/</span> {{ formattedMax }}
      </span>
    </div>
    <div class="h-2 overflow-hidden rounded-full bg-muted">
      <div
        class="h-full bg-foreground transition-[width] duration-300 ease-out"
        :style="{ width: `${percent}%` }"
      />
    </div>
  </div>
</template>

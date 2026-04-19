<script setup lang="ts">
defineProps<{
  label: string
  tokens: number
  cost?: number
}>()
</script>

<template>
  <div v-if="tokens > 0 || (cost || 0) > 0" class="flex items-center justify-between gap-4 text-[14px] leading-6">
    <span class="text-muted-foreground">{{ label }}</span>
    <span class="text-right text-foreground">
      <span class="font-medium">{{ tokens.toLocaleString("zh-CN") }}</span>
      <span v-if="(cost || 0) > 0" class="text-muted-foreground">
        <span class="px-2">•</span>${{ Number(cost || 0).toFixed(2) }}
      </span>
    </span>
  </div>
</template>

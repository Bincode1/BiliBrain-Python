<script setup lang="ts">
import { computed } from "vue"
import { useContextState } from "./context"

const { props } = useContextState()

const totalCost = computed(() => {
  const usage = props.usage || {}
  return Number(usage.totalCost || 0)
})
</script>

<template>
  <div v-if="totalCost > 0" class="border-t px-4 py-3">
    <div class="flex items-center justify-between text-[14px] leading-5">
      <span class="text-muted-foreground">Total cost</span>
      <span class="font-medium text-foreground">${{ totalCost.toFixed(2) }}</span>
    </div>
  </div>
</template>

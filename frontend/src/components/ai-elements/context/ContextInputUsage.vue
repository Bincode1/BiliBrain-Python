<script setup lang="ts">
import { computed } from "vue"
import ContextUsageRow from "./ContextUsageRow.vue"
import { useContextState } from "./context"

const { props } = useContextState()
const tokens = computed(() => Number(props.usage?.inputTokens || 0))
const cost = computed(() => Number(props.usage?.inputCost || 0))
</script>

<template>
  <ContextUsageRow label="Input" :tokens="tokens" :cost="cost" />
</template>

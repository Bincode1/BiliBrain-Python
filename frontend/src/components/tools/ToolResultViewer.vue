<template>
  <section class="tool-result-card">
    <div class="tool-result-head">
      <div>
        <span class="tool-panel-kicker">最近结果</span>
        <h3>{{ title }}</h3>
      </div>
      <span class="tool-result-badge" :class="{ error: isError }">{{ isError ? "失败" : "结果" }}</span>
    </div>

    <div v-if="summaryText" class="tool-result-summary">{{ summaryText }}</div>
    <pre class="tool-result-pre">{{ formattedPayload }}</pre>
  </section>
</template>

<script setup>
import { computed } from "vue";

const props = defineProps({
  result: {
    type: Object,
    default: null,
  },
});

const isError = computed(() => Boolean(props.result?.error));
const title = computed(() => props.result?.tool_name || props.result?.toolName || "工具输出");
const summaryText = computed(() => {
  if (!props.result) {
    return "";
  }
  if (props.result.error?.message) {
    return props.result.error.message;
  }
  if (props.result.payload?.stdout) {
    return String(props.result.payload.stdout).trim().slice(0, 180);
  }
  if (props.result.payload?.content) {
    return String(props.result.payload.content).trim().slice(0, 180);
  }
  if (props.result.payload?.items) {
    return `共返回 ${props.result.payload.items.length} 条记录。`;
  }
  if (props.result.payload?.results) {
    return `共返回 ${props.result.payload.results.length} 条搜索结果。`;
  }
  return "";
});
const formattedPayload = computed(() => JSON.stringify(props.result, null, 2));
</script>

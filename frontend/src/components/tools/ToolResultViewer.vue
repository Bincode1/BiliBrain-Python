<template>
  <Card>
    <CardHeader class="pb-2">
      <div class="flex items-start justify-between gap-2">
        <div>
          <span class="text-[10px] uppercase tracking-wider text-muted-foreground">最近结果</span>
          <CardTitle class="text-base">{{ title }}</CardTitle>
        </div>
        <Badge :variant="isError ? 'destructive' : 'default'">{{ isError ? "失败" : "结果" }}</Badge>
      </div>
    </CardHeader>
    <CardContent class="flex flex-col gap-3">
      <p v-if="summaryText" class="rounded-lg bg-muted px-3 py-2 text-xs">{{ summaryText }}</p>
      <pre class="max-h-[360px] overflow-auto rounded-lg border border-border/60 bg-muted/40 p-3 text-xs leading-relaxed">{{ formattedPayload }}</pre>
    </CardContent>
  </Card>
</template>

<script setup>
import { computed } from "vue";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

const props = defineProps({
  result: { type: Object, default: null },
});

const isError = computed(() => Boolean(props.result?.error));
const title = computed(() => props.result?.tool_name || props.result?.toolName || "工具输出");
const summaryText = computed(() => {
  if (!props.result) return "";
  if (props.result.error?.message) return props.result.error.message;
  if (props.result.payload?.stdout) return String(props.result.payload.stdout).trim().slice(0, 180);
  if (props.result.payload?.content) return String(props.result.payload.content).trim().slice(0, 180);
  if (props.result.payload?.items) return `共返回 ${props.result.payload.items.length} 条记录。`;
  if (props.result.payload?.results) return `共返回 ${props.result.payload.results.length} 条搜索结果。`;
  return "";
});
const formattedPayload = computed(() => JSON.stringify(props.result, null, 2));
</script>

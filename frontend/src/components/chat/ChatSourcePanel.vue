<template>
  <div v-if="sources?.length" class="mt-2 flex flex-col gap-2">
    <Sources :open="expanded" @update:open="$emit('toggle')">
      <!-- Header row (always visible) -->
      <div class="flex items-center justify-between">
        <span class="text-xs font-medium text-muted-foreground">{{ sourceLabel }}</span>
        <SourcesTrigger :count="sources.length">
          <span
            class="inline-flex items-center gap-1 h-6 px-2 rounded-md text-[11px] font-medium bg-secondary text-secondary-foreground hover:bg-primary/10 hover:text-primary transition-colors"
          >
            <svg
              xmlns="http://www.w3.org/2000/svg"
              class="h-3 w-3 transition-transform duration-200"
              :class="expanded ? 'rotate-180' : ''"
              viewBox="0 0 20 20"
              fill="currentColor"
            >
              <path fill-rule="evenodd" d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z" clip-rule="evenodd" />
            </svg>
            {{ expanded ? "收起来源" : `展开 ${sources.length} 条来源` }}
          </span>
        </SourcesTrigger>
      </div>

      <!-- Collapsed: compact chips (outside SourcesContent, always visible) -->
      <div v-if="!expanded" class="flex flex-wrap gap-1.5 mt-2">
        <a
          v-for="source in sources.slice(0, 3)"
          :key="`compact-${source.ref_index}`"
          :href="source.jump_url"
          target="_blank"
          rel="noreferrer"
          class="inline-flex items-center gap-1.5 max-w-[260px] truncate rounded-full border border-border bg-card px-2.5 py-0.5 text-[11px] hover:bg-secondary hover:border-primary/30 transition-colors"
        >
          <span class="shrink-0 rounded-full bg-primary/10 px-1.5 py-0 text-[10px] font-semibold text-primary">资料 {{ source.ref_index }}</span>
          <strong class="truncate">{{ previewTitle(source) }}</strong>
        </a>
        <span v-if="sources.length > 3" class="inline-flex items-center rounded-full bg-muted px-2 py-0.5 text-[11px] text-muted-foreground">
          还有 {{ sources.length - 3 }} 条
        </span>
      </div>

      <!-- Expanded: full list with Source components (toggled by Sources Collapsible) -->
      <SourcesContent>
        <div class="rounded-lg border border-border bg-card overflow-hidden mt-2">
          <div class="flex max-h-[220px] flex-col overflow-y-auto divide-y divide-border">
            <Source
              v-for="source in sources"
              :key="source.ref_index"
              :href="source.jump_url || '#'"
              :title="source.video_title || source.title || '未命名来源'"
              class="flex items-start gap-2.5 px-3 py-2 hover:bg-primary/5 transition-colors"
            >
              <span class="shrink-0 mt-0.5 rounded-full bg-primary/10 px-2 py-0.5 text-[10px] font-semibold text-primary">资料 {{ source.ref_index }}</span>
              <div class="flex flex-col gap-0.5 min-w-0">
                <strong class="truncate text-foreground text-xs">{{ source.video_title || source.title || source.url || "未命名来源" }}</strong>
                <span class="text-[10px] text-muted-foreground">{{ metaLabel(source) }}</span>
              </div>
            </Source>
          </div>
        </div>
      </SourcesContent>
    </Sources>
  </div>
</template>

<script setup>
import { sourcePreviewTitle, sourceMetaLabel } from "@/utils/chat";
import {
  Sources,
  SourcesTrigger,
  SourcesContent,
  Source,
} from "@/components/ai-elements/sources";

defineProps({
  sources: { type: Array, default: () => [] },
  expanded: { type: Boolean, default: false },
  sourceLabel: { type: String, default: "来源" },
});

defineEmits(["toggle"]);

function previewTitle(source) { return sourcePreviewTitle(source); }
function metaLabel(source) { return sourceMetaLabel(source); }
</script>

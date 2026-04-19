<template>
  <div v-if="sources?.length" class="mt-2">
    <Sources :open="expanded" @update:open="$emit('toggle')">
      <SourcesTrigger
        :count="sources.length"
        class="cursor-pointer text-[12px] font-medium text-primary"
      >
        <span>已使用 {{ sources.length }} 个来源</span>
      </SourcesTrigger>

      <SourcesContent class="w-full max-w-[min(100vw-2rem,32rem)]">
        <Source
          v-for="source in sources"
          :key="source.ref_index"
          :href="source.jump_url || '#'"
          :title="source.video_title || source.title || source.url || '未命名来源'"
          class="w-full items-start gap-3 rounded-lg px-3 py-2 text-left transition-colors hover:bg-accent/30"
        >
          <BookIcon class="mt-0.5 h-4 w-4 shrink-0 text-foreground/55" />
          <span class="min-w-0 flex-1">
            <strong class="block truncate text-[13px] font-medium leading-5 text-foreground">
              {{ source.video_title || source.title || source.url || "未命名来源" }}
            </strong>
            <span
              v-if="metaLabel(source)"
              class="block truncate text-[12px] leading-5 text-muted-foreground"
            >
              {{ metaLabel(source) }}
            </span>
          </span>
        </Source>
      </SourcesContent>
    </Sources>
  </div>
</template>

<script setup>
import { BookIcon } from "lucide-vue-next";
import { sourceMetaLabel } from "@/utils/chat";
import {
  Source,
  Sources,
  SourcesContent,
  SourcesTrigger,
} from "@/components/ai-elements/sources";

defineProps({
  sources: { type: Array, default: () => [] },
  expanded: { type: Boolean, default: false },
});

defineEmits(["toggle"]);

function metaLabel(source) { return sourceMetaLabel(source); }
</script>

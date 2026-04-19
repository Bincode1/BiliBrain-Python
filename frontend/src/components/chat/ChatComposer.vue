<template>
  <PromptInput
    class="rounded-lg bg-card shadow-sm [&>[data-slot=input-group]]:rounded-lg [&>[data-slot=input-group]]:border-border"
    @submit="handleSubmit"
  >
    <PromptInputTextarea
      :placeholder="chatPlaceholder"
      class="min-h-12 max-h-36 px-3.5 pt-2.5 pb-1 text-[14px] leading-6 placeholder:text-muted-foreground/40"
    />

    <PromptInputFooter class="flex items-center justify-between border-t border-border/50 px-2.5 py-2">
      <div class="flex min-w-0 flex-1 flex-wrap items-center gap-1.5 pr-3">
        <InlineSelect
          :model-value="scopeRootMode"
          :options="scopeRootOptions"
          title="选择问答范围"
          trigger-class="w-[120px] shrink-0"
          @update:model-value="handleScopeRootChange"
        />
        <InlineSelect
          v-if="scopeRootMode === 'folder'"
          :model-value="chatScopeFolderId"
          :options="folderOptions"
          :placeholder="folders.length ? '收藏夹' : '暂无'"
          :disabled="!folders.length"
          title="选择收藏夹"
          trigger-class="w-[140px] shrink-0"
          @update:model-value="handleScopeFolderChange"
        />
        <InlineSelect
          v-if="scopeRootMode === 'folder'"
          :model-value="scopeTargetValue"
          :options="scopeTargetOptions"
          :disabled="videoSelectDisabled"
          title="选择目标"
          trigger-class="min-w-[240px] max-w-[320px] flex-1"
          @update:model-value="handleScopeTargetChange"
        />
      </div>

      <div class="flex shrink-0 items-center gap-2">
        <div class="w-[120px]">
          <ChatContextIndicator />
        </div>
        <Button
          type="submit"
          size="sm"
          class="h-8 shrink-0 gap-1 rounded-full px-4 text-[13px] font-medium"
        >
          <svg class="size-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <path d="M5 12h14" /><path d="m12 5 7 7-7 7" />
          </svg>
          发送
        </Button>
      </div>
    </PromptInputFooter>
  </PromptInput>
</template>

<script setup>
import { computed } from "vue";
import { storeToRefs } from "pinia";

import ChatContextIndicator from "@/components/chat/ChatContextIndicator.vue";
import { Button } from "@/components/ui/button";
import InlineSelect from "@/components/chat/InlineSelect.vue";
import {
  PromptInput,
  PromptInputTextarea,
  PromptInputFooter,
} from "@/components/ai-elements/prompt-input";
import { useChatStore } from "@/stores/chat";
import { useFoldersStore } from "@/stores/folders";

const store = useChatStore();
const foldersStore = useFoldersStore();
const {
  chatPlaceholder,
  chatScopeFolderId,
  chatScopeMode,
  chatScopeVideos,
  selectedChatFolder,
  selectedChatVideo,
} = storeToRefs(store);
const { folders } = storeToRefs(foldersStore);

const scopeRootMode = computed(() => (chatScopeMode.value === "global" ? "global" : "folder"));
const scopeTargetValue = computed(() => (chatScopeMode.value === "video" && selectedChatVideo.value ? selectedChatVideo.value.bvid : "__all__"));

const scopeRootOptions = [
  { value: "folder", label: "收藏夹" },
  { value: "global", label: "全部已入库" },
];
const folderOptions = computed(() =>
  folders.value.map((f) => ({ value: String(f.folder_id), label: f.title }))
);
const scopeTargetOptions = computed(() => [
  { value: "__all__", label: "整个收藏夹" },
  ...chatScopeVideos.value.map((v) => ({ value: v.bvid, label: v.title })),
]);
const videoSelectDisabled = computed(() => !selectedChatFolder.value || selectedChatFolder.value.loadingVideos);

function handleSubmit(payload) {
  if (!payload.text?.trim()) return;
  // Fire-and-forget: store.askQuestion is async but we don't await it
  // so PromptInput clears the text input immediately
  store.askQuestion(payload.text);
}

async function handleScopeRootChange(value) { await store.setChatScopeRoot(value); }
async function handleScopeFolderChange(value) { await store.setChatScopeFolder(value); }
async function handleScopeTargetChange(value) { await store.setChatScopeTarget(value === "__all__" ? "" : value); }
</script>

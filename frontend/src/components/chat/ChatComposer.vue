<template>
  <div class="composer">
    <div class="composer-input-shell">
      <span class="composer-kicker">开始一轮新的提问</span>
      <textarea v-model="chatInput" :placeholder="chatPlaceholder" />
      <div class="composer-toolbar">
        <div class="composer-toolbar-main">
          <div class="composer-toolbar-group">
            <span class="composer-toolbar-label">方式</span>
            <InlineSelect v-model="chatMode" class="composer-scope-pill composer-mode-pill" :options="modeOptions" title="选择聊天模式" />
            <label v-if="chatMode === 'rag'" class="composer-toggle-pill" :class="{ active: deepResearchEnabled }">
              <input v-model="deepResearchEnabled" type="checkbox" />
              <span>深度研究</span>
            </label>
          </div>

          <div v-if="chatMode === 'rag'" class="composer-toolbar-group composer-toolbar-group-scope">
            <span class="composer-toolbar-label">范围</span>
            <div class="composer-scope-group composer-scope-grid">
              <InlineSelect
                class="composer-scope-pill composer-scope-root"
                :model-value="scopeRootMode"
                :options="scopeRootOptions"
                title="选择问答范围"
                @update:model-value="handleScopeRootChange"
              />
              <InlineSelect
                v-if="scopeRootMode === 'folder'"
                class="composer-scope-pill composer-folder-pill"
                :model-value="chatScopeFolderId"
                :options="folderOptions"
                :placeholder="folders.length ? '选择收藏夹' : '暂无收藏夹'"
                :disabled="!folders.length"
                title="选择收藏夹"
                @update:model-value="handleScopeFolderChange"
              />
              <InlineSelect
                v-if="scopeRootMode === 'folder'"
                class="composer-scope-pill composer-video-pill"
                :model-value="scopeTargetValue"
                :options="scopeTargetOptions"
                :disabled="videoSelectDisabled"
                title="选择收藏夹目标"
                @update:model-value="handleScopeTargetChange"
              />
            </div>
          </div>

          <div v-else class="composer-toolbar-summary">
            <span class="composer-summary-chip">{{ activeModeLabel }}</span>
            <strong>按当前启用技能直接执行</strong>
          </div>
        </div>

        <div class="composer-toolbar-side">
          <div v-if="chatMode === 'rag'" class="composer-toolbar-summary">
            <span class="composer-summary-chip">{{ scopeMetaLabel }}</span>
            <strong>{{ scopeSummary }}</strong>
            <span v-if="deepResearchEnabled" class="composer-summary-chip accent">深度研究</span>
          </div>
          <div v-else class="composer-toolbar-summary">
            <span class="composer-summary-chip accent">技能代理</span>
            <strong>直接执行当前任务</strong>
          </div>
          <button class="composer-submit-button" type="button" @click="store.askQuestion">发送</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from "vue";
import { storeToRefs } from "pinia";

import InlineSelect from "@/components/chat/InlineSelect.vue";
import { useWorkspaceStore } from "@/stores/workspace";

defineProps({
  folderOnly: {
    type: Boolean,
    default: false,
  },
});

const store = useWorkspaceStore();
const {
  chatInput,
  chatMode,
  deepResearchEnabled,
  chatPlaceholder,
  chatScopeFolderId,
  chatScopeMode,
  chatScopeVideos,
  folders,
  selectedChatFolder,
  selectedChatVideo,
} = storeToRefs(store);

const scopeRootMode = computed(() => (chatScopeMode.value === "global" ? "global" : "folder"));

const scopeTargetValue = computed(() => (chatScopeMode.value === "video" && selectedChatVideo.value ? selectedChatVideo.value.bvid : "__all__"));

const modeOptions = [
  { value: "rag", label: "知识问答" },
  { value: "skill_agent", label: "技能代理" },
];

const scopeRootOptions = [
  { value: "folder", label: "收藏夹" },
  { value: "global", label: "全部已入库" },
];

const folderOptions = computed(() =>
  folders.value.map((folder) => ({
    value: String(folder.folder_id),
    label: folder.title,
  }))
);

const scopeTargetOptions = computed(() => [
  { value: "__all__", label: "整个收藏夹" },
  ...chatScopeVideos.value.map((video) => ({
    value: video.bvid,
    label: video.title,
  })),
]);

const videoSelectDisabled = computed(() => {
  if (!selectedChatFolder.value) return true;
  if (selectedChatFolder.value.loadingVideos) return true;
  return false;
});

const activeModeLabel = computed(() => modeOptions.find((option) => option.value === chatMode.value)?.label || "知识问答");

const scopeSummary = computed(() => {
  if (scopeRootMode.value === "global") {
    return "全部已入库";
  }
  if (chatScopeMode.value === "folder") {
    return selectedChatFolder.value?.title || "先选一个收藏夹";
  }
  if (!selectedChatFolder.value) {
    return "先选一个收藏夹";
  }
  return selectedChatVideo.value
    ? `${selectedChatFolder.value.title} / ${selectedChatVideo.value.title}`
    : `${selectedChatFolder.value.title} / 整个收藏夹`;
});

const scopeMetaLabel = computed(() => {
  if (scopeRootMode.value === "global") {
    return "全库范围";
  }
  if (chatScopeMode.value === "video") {
    return "单视频范围";
  }
  return "收藏夹范围";
});

async function handleScopeRootChange(value) {
  await store.setChatScopeRoot(value);
}

async function handleScopeFolderChange(value) {
  await store.setChatScopeFolder(value);
}

async function handleScopeTargetChange(value) {
  const nextValue = value === "__all__" ? "" : value;
  await store.setChatScopeTarget(nextValue);
}
</script>

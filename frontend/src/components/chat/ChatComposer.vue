<template>
  <div class="composer">
    <textarea v-model="chatInput" :placeholder="chatPlaceholder" />
    <div class="composer-toolbar">
      <div class="composer-scope-group">
        <label class="composer-scope-pill">
          <select
            v-model="chatScopeMode"
            :title="chatScopeMode === 'video' ? (selectedVideo?.title || '当前视频') : (chatScopeMode === 'folder' ? (selectedChatFolder?.title || '指定收藏夹') : '全部已入库')"
          >
            <option value="video">当前视频</option>
            <option value="folder">指定收藏夹</option>
            <option value="global">全部已入库</option>
          </select>
        </label>
        <label v-if="chatScopeMode === 'folder'" class="composer-scope-pill composer-folder-pill">
          <select v-model="chatScopeFolderId" :disabled="!folders.length" title="选择收藏夹">
            <option value="" disabled>{{ folders.length ? "选择收藏夹" : "暂无收藏夹" }}</option>
            <option v-for="folder in folders" :key="folder.folder_id" :value="String(folder.folder_id)">
              {{ folder.title }}
            </option>
          </select>
        </label>
      </div>
      <button type="button" @click="store.askQuestion">发送</button>
    </div>
  </div>
</template>

<script setup>
import { storeToRefs } from "pinia";

import { useWorkspaceStore } from "@/stores/workspace";

const store = useWorkspaceStore();
const {
  chatInput,
  chatPlaceholder,
  chatScopeFolderId,
  chatScopeMode,
  folders,
  selectedChatFolder,
  selectedVideo,
} = storeToRefs(store);
</script>

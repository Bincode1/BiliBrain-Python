<template>
  <div v-if="folderSearchOpen" class="modal-shell folder-search-shell" @click.self="closeFolderSearch">
    <div class="modal-card folder-search-modal">
      <div class="folder-search-head">
        <div class="folder-search-copy">
          <div class="side-card-label">B 站相关视频</div>
          <h2 :title="folderSearchFolder?.title || '收藏夹搜索'">{{ folderSearchFolder?.title || "收藏夹搜索" }}</h2>
          <p>默认用收藏夹标题去 B 站搜索。你也可以改关键词后重新搜索。</p>
        </div>
        <button class="ghost-button small" type="button" @click="closeFolderSearch">关闭</button>
      </div>

      <div class="folder-search-toolbar">
        <label class="folder-search-field">
          <span class="app-dialog-label">关键词</span>
          <input
            ref="inputEl"
            v-model="folderSearchQuery"
            class="app-dialog-input"
            type="text"
            placeholder="例如：LangGraph / Django / RAG"
            @keydown.enter.prevent="searchBiliVideosForFolder()"
            @keydown.esc.prevent="closeFolderSearch"
          />
        </label>
        <button class="folder-search-submit" type="button" :disabled="folderSearchLoading || !trimmedQuery" @click="searchBiliVideosForFolder()">
          {{ folderSearchLoading ? "搜索中..." : "搜索 B 站" }}
        </button>
        <label class="folder-search-page-size">
          <span class="app-dialog-label">每页</span>
          <select v-model="pageSize" :disabled="folderSearchLoading" @change="searchBiliVideosForFolder({ page: 1 })">
            <option :value="12">12 条</option>
            <option :value="24">24 条</option>
            <option :value="30">30 条</option>
          </select>
        </label>
      </div>

      <div class="folder-search-meta">
        <span class="document-kind-chip">关键词 {{ trimmedQuery || "未填写" }}</span>
        <span v-if="folderSearchSearched">命中约 {{ formatCount(folderSearchTotal) }} 条</span>
        <span v-if="folderSearchSearched && folderSearchResults.length">
          当前显示 {{ visibleStart }}-{{ visibleEnd }} / {{ formatCount(folderSearchTotal) }}
        </span>
        <span v-else>打开后会自动发起一次搜索</span>
      </div>

      <div v-if="folderSearchLoading" class="folder-search-empty">正在从 B 站搜索相关视频...</div>
      <div v-else-if="folderSearchError" class="folder-search-empty danger-text">{{ folderSearchError }}</div>
      <div v-else-if="folderSearchSearched && !folderSearchResults.length" class="folder-search-empty">
        没有找到相关视频，换个关键词再试试。
      </div>
      <div v-else-if="folderSearchResults.length" class="folder-search-results">
        <div class="folder-search-pager">
          <button class="ghost-button small" type="button" :disabled="folderSearchLoading || currentPage <= 1" @click="searchBiliVideosForFolder({ page: currentPage - 1 })">
            上一页
          </button>
          <div class="folder-search-page-indicator">
            第 {{ currentPage }} / {{ totalPages }} 页
          </div>
          <button class="ghost-button small" type="button" :disabled="folderSearchLoading || currentPage >= totalPages" @click="searchBiliVideosForFolder({ page: currentPage + 1 })">
            下一页
          </button>
        </div>

        <button
          v-for="video in folderSearchResults"
          :key="video.bvid"
          class="folder-search-result"
          type="button"
          @click="openFolderSearchResult(video)"
        >
          <div
            class="folder-search-cover"
            :class="{ empty: !video.cover_url }"
          >
            <img
              v-if="video.cover_url && !video.coverLoadFailed"
              :src="video.cover_url"
              :alt="video.title"
              loading="lazy"
              referrerpolicy="no-referrer"
              @error="video.coverLoadFailed = true"
            />
            <span v-else>封面</span>
          </div>

          <div class="folder-search-body">
            <div class="folder-search-row">
              <strong>{{ video.title }}</strong>
              <div class="folder-search-actions">
                <span class="folder-search-chip">{{ video.duration_text || "--:--" }}</span>
                <span class="video-link-chip" @click.stop="openFolderSearchResult(video)">打开</span>
              </div>
            </div>

            <div class="folder-search-stats">
              <span>{{ video.up_name || "未知 UP" }}</span>
              <span>{{ formatCount(video.play_count) }} 播放</span>
              <span>{{ formatCount(video.favorites) }} 收藏</span>
              <span>{{ formatDate(video.published_at) }}</span>
            </div>

            <p v-if="video.description" class="folder-search-desc">
              {{ video.description }}
            </p>

            <div v-if="video.tag_text" class="folder-search-tags">
              {{ video.tag_text }}
            </div>

            <div class="folder-search-foot">
              <span>{{ video.bvid }}</span>
              <span>来自 B 站搜索结果</span>
            </div>
          </div>
        </button>
      </div>
      <div v-else class="folder-search-empty">
        输入关键词后可重新搜索，不会影响当前页面布局和已选中的视频。
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, ref, watch } from "vue";
import { storeToRefs } from "pinia";

import { api } from "@/services/http";
import { useWorkspaceStore } from "@/stores/workspace";

const store = useWorkspaceStore();
const {
  folderSearchError,
  folderSearchFolder,
  folderSearchFolderId,
  folderSearchLoading,
  folderSearchOpen,
  folderSearchQuery,
  folderSearchResults,
  folderSearchSearched,
  folderSearchTotal,
} = storeToRefs(store);
const inputEl = ref(null);
const currentPage = ref(1);
const pageSize = ref(12);

const trimmedQuery = computed(() => folderSearchQuery.value.trim());
const totalPages = computed(() => Math.max(1, Math.ceil(Number(folderSearchTotal.value || 0) / Number(pageSize.value || 12))));
const visibleStart = computed(() => {
  if (!folderSearchResults.value.length) {
    return 0;
  }
  return (Number(currentPage.value || 1) - 1) * Number(pageSize.value || 12) + 1;
});
const visibleEnd = computed(() => {
  if (!folderSearchResults.value.length) {
    return 0;
  }
  return visibleStart.value + folderSearchResults.value.length - 1;
});

function formatCount(value) {
  const count = Number(value || 0);
  if (count >= 10000) {
    return `${(count / 10000).toFixed(count >= 100000 ? 0 : 1)}万`;
  }
  return String(count);
}

function formatDate(value) {
  if (!value) {
    return "时间未知";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "时间未知";
  }
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

function closeFolderSearch() {
  store.closeFolderSearch();
}

function openFolderSearchResult(video) {
  const url = String(video?.watch_url || "");
  if (!url) {
    return;
  }
  window.open(url, "_blank", "noopener,noreferrer");
}

async function searchBiliVideosForFolder(options = {}) {
  const normalizedFolderId = Number(folderSearchFolderId.value || 0);
  const normalizedKeyword = trimmedQuery.value;
  const targetPage = Math.max(Number(options.page || currentPage.value || 1), 1);
  if (!normalizedFolderId || !normalizedKeyword) {
    return;
  }

  folderSearchLoading.value = true;
  folderSearchError.value = "";
  folderSearchSearched.value = true;
  try {
    const params = new URLSearchParams();
    params.set("keyword", normalizedKeyword);
    params.set("page", String(targetPage));
    params.set("page_size", String(pageSize.value));
    const data = await api(`/api/folders/${normalizedFolderId}/bili-search?${params.toString()}`);
    folderSearchQuery.value = data.keyword || normalizedKeyword;
    folderSearchResults.value = Array.isArray(data.results) ? data.results : [];
    folderSearchTotal.value = Number(data.total || folderSearchResults.value.length || 0);
    currentPage.value = Number(data.page || targetPage);
    pageSize.value = Number(data.page_size || pageSize.value || 12);
  } catch (error) {
    folderSearchResults.value = [];
    folderSearchTotal.value = 0;
    folderSearchError.value = error.message;
  } finally {
    folderSearchLoading.value = false;
  }
}

watch(folderSearchOpen, async (open) => {
  if (!open) {
    return;
  }
  currentPage.value = 1;
  pageSize.value = 12;
  await nextTick();
  inputEl.value?.focus?.();
});
</script>

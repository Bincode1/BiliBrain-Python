<template>
  <Dialog :open="folderSearchOpen" @update:open="(v) => { if (!v) closeFolderSearch() }">
    <DialogContent class="max-w-4xl max-h-[calc(100vh-48px)] overflow-auto">
      <DialogHeader>
        <DialogDescription class="text-[10px] uppercase tracking-wider text-muted-foreground">B 站相关视频</DialogDescription>
        <DialogTitle>{{ folderSearchFolder?.title || "收藏夹搜索" }}</DialogTitle>
        <p class="text-xs text-muted-foreground">默认用收藏夹标题去 B 站搜索。你也可以改关键词后重新搜索。</p>
      </DialogHeader>

      <!-- Search toolbar -->
      <div class="flex flex-wrap items-end gap-3">
        <div class="flex flex-col gap-1 min-w-[220px] flex-1">
          <label class="text-[10px] uppercase tracking-wider text-muted-foreground">关键词</label>
          <Input
            ref="inputEl"
            v-model="folderSearchQuery"
            placeholder="例如：LangGraph / Django / RAG"
            @keydown.enter.prevent="searchBiliVideosForFolder()"
          />
        </div>
        <Button :disabled="folderSearchLoading || !trimmedQuery" @click="searchBiliVideosForFolder()">
          {{ folderSearchLoading ? "搜索中..." : "搜索 B 站" }}
        </Button>
        <div class="flex flex-col gap-1">
          <label class="text-[10px] uppercase tracking-wider text-muted-foreground">每页</label>
          <Select v-model="pageSize" :disabled="folderSearchLoading" @update:model-value="searchBiliVideosForFolder({ page: 1 })">
            <SelectTrigger class="w-24 h-9">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem :value="12">12 条</SelectItem>
              <SelectItem :value="24">24 条</SelectItem>
              <SelectItem :value="30">30 条</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      <!-- Meta line -->
      <div class="flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
        <Badge variant="outline" class="text-[10px]">关键词 {{ trimmedQuery || "未填写" }}</Badge>
        <span v-if="folderSearchSearched">命中约 {{ formatCount(folderSearchTotal) }} 条</span>
        <span v-if="folderSearchSearched && folderSearchResults.length">
          当前显示 {{ visibleStart }}-{{ visibleEnd }} / {{ formatCount(folderSearchTotal) }}
        </span>
      </div>

      <!-- Loading / error / empty -->
      <div v-if="folderSearchLoading" class="py-10 text-center text-sm text-muted-foreground">正在从 B 站搜索相关视频...</div>
      <div v-else-if="folderSearchError" class="rounded-lg bg-destructive/10 px-4 py-3 text-sm text-destructive">{{ folderSearchError }}</div>
      <div v-else-if="folderSearchSearched && !folderSearchResults.length" class="py-10 text-center text-sm text-muted-foreground">
        没有找到相关视频，换个关键词再试试。
      </div>

      <!-- Results -->
      <div v-else-if="folderSearchResults.length" class="flex flex-col gap-3">
        <!-- Pager -->
        <div class="sticky top-0 z-10 flex items-center justify-between gap-3 rounded-lg border border-border bg-card px-3 py-2">
          <Button size="sm" variant="outline" :disabled="folderSearchLoading || currentPage <= 1" @click="searchBiliVideosForFolder({ page: currentPage - 1 })">
            上一页
          </Button>
          <span class="text-xs font-semibold text-primary">第 {{ currentPage }} / {{ totalPages }} 页</span>
          <Button size="sm" variant="outline" :disabled="folderSearchLoading || currentPage >= totalPages" @click="searchBiliVideosForFolder({ page: currentPage + 1 })">
            下一页
          </Button>
        </div>

        <!-- Result cards -->
        <Card
          v-for="video in folderSearchResults"
          :key="video.bvid"
          class="cursor-pointer transition-all hover:shadow-md"
          @click="openFolderSearchResult(video)"
        >
          <CardContent class="flex gap-4 p-4">
            <!-- Cover -->
            <div class="h-[72px] w-[104px] shrink-0 overflow-hidden rounded-lg bg-muted">
              <img
                v-if="video.cover_url && !video.coverLoadFailed"
                :src="video.cover_url"
                :alt="video.title"
                loading="lazy"
                referrerpolicy="no-referrer"
                class="h-full w-full object-cover"
                @error="video.coverLoadFailed = true"
              />
              <span v-else class="flex h-full items-center justify-center text-[10px] text-muted-foreground">封面</span>
            </div>

            <!-- Body -->
            <div class="min-w-0 flex-1">
              <div class="flex items-start justify-between gap-2">
                <strong class="line-clamp-2 text-sm">{{ video.title }}</strong>
                <div class="flex shrink-0 items-center gap-2">
                  <Badge variant="secondary" class="text-[10px]">{{ video.duration_text || "--:--" }}</Badge>
                </div>
              </div>

              <div class="mt-1 flex flex-wrap gap-2 text-[11px] text-muted-foreground">
                <span>{{ video.up_name || "未知 UP" }}</span>
                <span>{{ formatCount(video.play_count) }} 播放</span>
                <span>{{ formatCount(video.favorites) }} 收藏</span>
                <span>{{ formatDate(video.published_at) }}</span>
              </div>

              <p v-if="video.description" class="mt-1 line-clamp-2 text-xs text-muted-foreground">{{ video.description }}</p>

              <div class="mt-1 flex items-center justify-between text-[10px] text-muted-foreground">
                <span>{{ video.bvid }}</span>
                <span>来自 B 站搜索结果</span>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      <div v-else class="py-10 text-center text-sm text-muted-foreground">
        输入关键词后可重新搜索，不会影响当前页面布局和已选中的视频。
      </div>
    </DialogContent>
  </Dialog>
</template>

<script setup>
import { computed, nextTick, ref, watch } from "vue";
import { storeToRefs } from "pinia";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

import { api } from "@/services/http";
import { useFolderSearchStore } from "@/stores/folderSearch";

const store = useFolderSearchStore();
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
  if (!folderSearchResults.value.length) return 0;
  return (Number(currentPage.value || 1) - 1) * Number(pageSize.value || 12) + 1;
});
const visibleEnd = computed(() => {
  if (!folderSearchResults.value.length) return 0;
  return visibleStart.value + folderSearchResults.value.length - 1;
});

function formatCount(value) {
  const count = Number(value || 0);
  if (count >= 10000) return `${(count / 10000).toFixed(count >= 100000 ? 0 : 1)}万`;
  return String(count);
}

function formatDate(value) {
  if (!value) return "时间未知";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "时间未知";
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

function closeFolderSearch() { store.closeFolderSearch(); }

function openFolderSearchResult(video) {
  const url = String(video?.watch_url || "");
  if (!url) return;
  window.open(url, "_blank", "noopener,noreferrer");
}

async function searchBiliVideosForFolder(options = {}) {
  const normalizedFolderId = Number(folderSearchFolderId.value || 0);
  const normalizedKeyword = trimmedQuery.value;
  const targetPage = Math.max(Number(options.page || currentPage.value || 1), 1);
  if (!normalizedFolderId || !normalizedKeyword) return;

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
  if (!open) return;
  currentPage.value = 1;
  pageSize.value = 12;
  await nextTick();
  inputEl.value?.$el?.querySelector?.("input")?.focus?.() || inputEl.value?.focus?.();
});
</script>

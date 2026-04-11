<template>
  <section class="flex flex-1 flex-col gap-4 overflow-auto p-4">
    <div class="flex items-center justify-between">
      <div>
        <span class="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">收藏夹</span>
        <h2 class="mt-0.5 text-xl font-semibold" :style="{ fontSize: 'clamp(24px, 2.6vw, 34px)' }">
          {{ selectedFolder ? selectedFolder.title : "选择一个收藏夹" }}
        </h2>
      </div>
      <p class="text-sm text-muted-foreground">{{ selectedFolder ? `${selectedFolder.media_count || 0} 个视频` : "右侧直接铺开视频卡片" }}</p>
    </div>

    <!-- No folder selected -->
    <div v-if="!selectedFolder" class="flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-border px-8 py-10 text-center">
      <strong class="text-sm">先从左侧选一个收藏夹</strong>
      <p class="text-xs text-muted-foreground">视频会像 B 站一样在右侧直接铺开。</p>
    </div>

    <!-- Loading -->
    <div v-else-if="selectedFolder.loadingVideos" class="flex items-center justify-center py-10 text-sm text-muted-foreground">
      正在读取视频列表...
    </div>

    <!-- Error -->
    <div v-else-if="selectedFolder.videoError" class="flex items-center justify-center py-10 text-sm text-destructive">
      {{ selectedFolder.videoError }}
    </div>

    <!-- Video grid -->
    <section v-else-if="selectedFolder.videos.length" class="grid grid-cols-[repeat(auto-fill,minmax(240px,1fr))] gap-4">
      <article
        v-for="video in selectedFolder.videos"
        :key="video.bvid"
        class="flex flex-col overflow-hidden rounded-lg border transition-all"
        :class="[
          {
            'ring-2 ring-primary border-primary': selectedVideo?.bvid === video.bvid && !video.is_invalid,
            'opacity-50 pointer-events-none': video.is_invalid,
          },
        ]"
      >
        <!-- Cover -->
        <button
          class="aspect-[16/10] w-full overflow-hidden bg-muted"
          :disabled="video.is_invalid"
          @click="foldersStore.selectVideo(selectedFolder, video)"
        >
          <img
            v-if="video.cover_url && !video.coverLoadFailed"
            :src="video.cover_url"
            :alt="video.title"
            loading="lazy"
            referrerpolicy="no-referrer"
            class="h-full w-full object-cover"
            @error="video.coverLoadFailed = true"
          />
          <span v-else class="flex h-full w-full items-center justify-center text-xs text-muted-foreground">{{ video.is_invalid ? "失效视频" : "暂无封面" }}</span>
        </button>

        <!-- Info -->
        <div class="flex flex-col gap-1.5 p-3">
          <div class="flex items-center justify-between">
            <span class="inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 text-[10px] font-medium" :class="statusToneClass(video)">
              <span class="size-1.5 rounded-full" :class="statusDotClass(video)"></span>
              {{ video.is_invalid ? "已失效" : syncStatusLabel(video.sync_status) }}
            </span>
            <Button v-if="video.watch_url" variant="ghost" size="sm" class="h-5 text-[10px]" @click="openVideoLink(video)">打开</Button>
          </div>
          <button
            class="text-left text-sm font-medium leading-snug line-clamp-2 hover:text-primary transition-colors"
            :disabled="video.is_invalid"
            @click="foldersStore.selectVideo(selectedFolder, video)"
          >
            {{ video.title }}
          </button>
          <div class="flex gap-2 text-[11px] text-muted-foreground">
            <span>{{ formatDuration(video.duration) }}</span>
            <span>{{ video.up_name || "未知 UP" }}</span>
            <span>片段 {{ video.chunk_count || 0 }}</span>
          </div>
        </div>

        <!-- Actions (always visible) -->
        <div v-if="!video.is_invalid" class="grid grid-cols-2 gap-1.5 border-t border-border p-2">
          <Button size="sm" class="h-7 text-[11px]" :disabled="video.processBusy || video.sync_status === 'indexed'" @click="handleProcess(video)">
            {{ video.processBusy ? "处理中..." : (video.processActionLabel || "处理") }}
          </Button>
          <Button variant="outline" size="sm" class="h-7 text-[11px]" :disabled="video.resetBusy" @click="handleReset(video)">
            {{ video.resetBusy ? "重置中" : "重置" }}
          </Button>
          <Button variant="outline" size="sm" class="h-7 text-[11px]" :disabled="!(canOpenSummary(video) || canGenerateSummary(video))" @click="handleSummary(video)">
            {{ video.summaryBusy ? "生成中" : (video.has_summary ? "摘要" : "生成摘要") }}
          </Button>
          <Button variant="outline" size="sm" class="h-7 text-[11px]" :disabled="!canOpenTranscript(video)" @click="handleTranscript(video)">
            转写
          </Button>
        </div>
      </article>
    </section>

    <!-- Empty folder -->
    <section v-else class="flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-border px-8 py-10 text-center">
      <strong class="text-sm">这个收藏夹还没有视频</strong>
      <p class="text-xs text-muted-foreground">先同步一次，或者去搜 B 站补内容。</p>
    </section>
  </section>
</template>

<script setup>
import { storeToRefs } from "pinia";

import { Button } from "@/components/ui/button";

import { useDocumentViewerStore } from "@/stores/documentViewer";
import { useFoldersStore } from "@/stores/folders";
import {
  canGenerateSummary,
  canOpenSummary,
  canOpenTranscript,
  formatDuration,
  openVideoLink,
  syncStatusLabel,
  videoTone,
} from "@/utils/video";

const docStore = useDocumentViewerStore();
const foldersStore = useFoldersStore();
const { selectedFolder, selectedVideo } = storeToRefs(foldersStore);

function statusToneClass(video) {
  if (video.is_invalid) return "bg-red-50 text-red-700";
  const tone = videoTone(video);
  if (tone === "done" || tone === "indexed") return "bg-emerald-50 text-emerald-700";
  if (tone === "processing") return "bg-amber-50 text-amber-700";
  if (tone === "failed") return "bg-red-50 text-red-700";
  if (tone === "partial") return "bg-orange-50 text-orange-700";
  return "bg-secondary text-muted-foreground";
}

function statusDotClass(video) {
  if (video.is_invalid) return "bg-red-500";
  const tone = videoTone(video);
  if (tone === "done" || tone === "indexed") return "bg-emerald-500";
  if (tone === "processing") return "bg-amber-500 animate-pulse";
  if (tone === "failed") return "bg-red-500";
  if (tone === "partial") return "bg-orange-500";
  return "bg-muted-foreground";
}

async function focusVideo(video) {
  if (!selectedFolder.value || video.is_invalid) return;
  foldersStore.selectVideo(selectedFolder.value, video);
}

async function handleProcess(video) { await focusVideo(video); await foldersStore.processSelectedVideo(); }
async function handleReset(video) { await focusVideo(video); await foldersStore.resetSelectedVideo(); }
async function handleSummary(video) {
  await focusVideo(video);
  if (video.has_summary) { await docStore.openDocumentViewer("summary", video); return; }
  await foldersStore.generateSummary(video);
}
async function handleTranscript(video) { await focusVideo(video); await docStore.openDocumentViewer("transcript", video); }
</script>

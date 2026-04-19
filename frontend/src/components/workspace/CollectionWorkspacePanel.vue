<template>
  <section class="flex flex-1 flex-col gap-3 overflow-auto bg-[color-mix(in_oklab,var(--background)_88%,white)] p-3">
    <div class="flex items-end justify-between gap-4 border-b border-border pb-3">
      <div>
        <span class="text-[11px] font-semibold uppercase tracking-[0.08em] text-foreground/74">收藏夹</span>
        <h2 class="mt-0.5 text-[1.5rem] font-semibold leading-tight text-foreground" :style="{ fontSize: 'clamp(1.5rem, 2vw, 2rem)' }">
          {{ selectedFolder ? selectedFolder.title : "选择一个收藏夹" }}
        </h2>
      </div>
      <p class="text-[13px] font-medium text-foreground/72">{{ selectedFolder ? `${selectedFolder.media_count || 0} 个视频` : "右侧直接铺开视频卡片" }}</p>
    </div>

    <!-- No folder selected -->
    <div v-if="!selectedFolder" class="flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-border px-8 py-10 text-center">
      <strong class="text-sm">先从左侧选一个收藏夹</strong>
      <p class="text-[13px] text-foreground/72">视频会像 B 站一样在右侧直接铺开。</p>
    </div>

    <!-- Loading -->
    <div v-else-if="selectedFolder.loadingVideos" class="flex items-center justify-center py-10 text-sm text-foreground/72">
      正在读取视频列表...
    </div>

    <!-- Error -->
    <div v-else-if="selectedFolder.videoError" class="flex items-center justify-center py-10 text-sm text-destructive">
      {{ selectedFolder.videoError }}
    </div>

    <!-- Video grid -->
    <section v-else-if="selectedFolder.videos.length" class="grid grid-cols-[repeat(auto-fill,minmax(258px,1fr))] gap-3">
      <article
        v-for="video in selectedFolder.videos"
        :key="video.bvid"
        class="group grid min-h-[364px] grid-rows-[auto_1fr_auto] overflow-hidden rounded-lg border border-border bg-card shadow-[var(--shadow-soft)] transition-all duration-150"
        :class="[
          {
            'cursor-pointer hover:-translate-y-0.5 hover:bg-[color-mix(in_oklab,var(--primary)_3.5%,white)] hover:shadow-[var(--shadow)]': !video.is_invalid,
            'bg-[color-mix(in_oklab,var(--primary)_3.5%,white)] shadow-[var(--shadow-soft)]': selectedVideo?.bvid === video.bvid && !video.is_invalid,
            'opacity-50 pointer-events-none': video.is_invalid,
          },
        ]"
        :tabindex="video.is_invalid ? -1 : 0"
        @click="handleCardSelect(video)"
        @keydown.enter.prevent="handleCardSelect(video)"
        @keydown.space.prevent="handleCardSelect(video)"
      >
        <!-- Cover -->
        <div class="aspect-[16/10] w-full overflow-hidden bg-muted">
          <img
            v-if="video.cover_url && !video.coverLoadFailed"
            :src="video.cover_url"
            :alt="video.title"
            loading="lazy"
            referrerpolicy="no-referrer"
            class="h-full w-full object-cover transition-transform duration-200 group-hover:scale-[1.02]"
            @error="video.coverLoadFailed = true"
          />
          <span v-else class="flex h-full w-full items-center justify-center text-sm font-medium text-foreground/70">{{ video.is_invalid ? "失效视频" : "暂无封面" }}</span>
        </div>

        <!-- Info -->
        <div class="grid min-h-0 grid-rows-[auto_auto_1fr_auto] gap-2 p-3">
          <div class="flex items-center justify-between">
            <span class="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium" :class="statusToneClass(video)">
              <span class="size-1.5 rounded-full" :class="statusDotClass(video)"></span>
              {{ video.is_invalid ? "已失效" : syncStatusLabel(video.sync_status) }}
            </span>
            <Button v-if="video.watch_url" variant="ghost" size="sm" class="h-6 px-2 text-[11px]" @click.stop="openVideoLink(video)">打开</Button>
          </div>
          <div
            class="min-h-[2.7rem] text-left text-[15px] font-semibold leading-5 text-foreground line-clamp-2 transition-colors group-hover:text-primary"
          >
            {{ video.title }}
          </div>
          <div class="grid grid-cols-2 gap-x-3 gap-y-1 text-[12px] font-medium leading-4 text-foreground/76">
            <span class="truncate">时长 {{ formatDuration(video.duration) }}</span>
            <span class="truncate text-right">片段 {{ video.chunk_count || 0 }}</span>
            <span class="col-span-2 truncate">UP {{ video.up_name || "未知 UP" }}</span>
          </div>
          <div class="flex flex-wrap items-center gap-1.5 text-[11px] font-medium text-foreground/78">
            <span class="rounded-md bg-secondary/90 px-1.5 py-0.5">{{ transcriptStateLabel(video) }}</span>
            <span class="rounded-md bg-secondary/90 px-1.5 py-0.5">{{ summaryButtonLabel(video) }}</span>
          </div>
        </div>

        <!-- Actions (always visible) -->
        <div v-if="!video.is_invalid" class="grid grid-cols-2 gap-1.5 border-t border-border bg-[color-mix(in_oklab,var(--background)_35%,white)] p-2">
          <Button size="sm" class="h-8 text-[11px]" :disabled="video.processBusy || video.sync_status === 'indexed'" @click.stop="handleProcess(video)">
            {{ processButtonLabel(video) }}
          </Button>
          <Button variant="outline" size="sm" class="h-8 text-[11px]" :disabled="video.resetBusy" @click.stop="handleReset(video)">
            {{ resetButtonLabel(video) }}
          </Button>
          <Button variant="outline" size="sm" class="h-8 text-[11px]" :disabled="!(canOpenSummary(video) || canGenerateSummary(video))" @click.stop="handleSummary(video)">
            {{ summaryButtonLabel(video) }}
          </Button>
          <Button variant="outline" size="sm" class="h-8 text-[11px]" :disabled="!canOpenTranscript(video)" @click.stop="handleTranscript(video)">
            {{ transcriptButtonLabel(video) }}
          </Button>
        </div>
      </article>
    </section>

    <!-- Empty folder -->
    <section v-else class="flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-border px-8 py-10 text-center">
      <strong class="text-sm">这个收藏夹还没有视频</strong>
      <p class="text-[13px] text-foreground/72">先同步一次，或者去搜 B 站补内容。</p>
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
  hasTranscript,
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
  if (tone === "done" || tone === "indexed") return "bg-[color-mix(in_oklab,var(--primary)_12%,white)] text-primary";
  if (tone === "processing") return "bg-amber-50 text-amber-700";
  if (tone === "failed") return "bg-red-50 text-red-700";
  if (tone === "partial") return "bg-sky-50 text-sky-700";
  return "bg-secondary/90 text-foreground/72";
}

function statusDotClass(video) {
  if (video.is_invalid) return "bg-red-500";
  const tone = videoTone(video);
  if (tone === "done" || tone === "indexed") return "bg-emerald-500";
  if (tone === "processing") return "bg-amber-500 animate-pulse";
  if (tone === "failed") return "bg-red-500";
  if (tone === "partial") return "bg-sky-500";
  return "bg-muted-foreground";
}

function processButtonLabel(video) {
  if (video.processBusy) return "处理中...";
  if (video.sync_status === "indexed") return "已入库";
  return video.processActionLabel || "开始处理";
}

function resetButtonLabel(video) {
  if (video.resetBusy) return "重新切片中";
  return "重新切片";
}

function summaryButtonLabel(video) {
  if (video.summaryBusy) return "生成中";
  if (video.has_summary) return "查看摘要";
  return "生成摘要";
}

function transcriptButtonLabel(video) {
  if (hasTranscript(video)) return "查看转写";
  return "转写";
}

function transcriptStateLabel(video) {
  return hasTranscript(video) ? "已转写" : "未转写";
}

async function focusVideo(video) {
  if (!selectedFolder.value || video.is_invalid) return;
  foldersStore.selectVideo(selectedFolder.value, video);
}

function handleCardSelect(video) {
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

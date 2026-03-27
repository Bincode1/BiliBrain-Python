<template>
  <section class="collection-stage">
    <div class="collection-stage-head">
      <div>
        <span class="page-section-kicker">收藏夹</span>
        <h2>{{ selectedFolder ? selectedFolder.title : "选择一个收藏夹" }}</h2>
      </div>
      <p>{{ selectedFolder ? `${selectedFolder.media_count || 0} 个视频` : "右侧直接铺开视频卡片" }}</p>
    </div>

    <section v-if="!selectedFolder" class="collection-empty-panel">
      <strong>先从左侧选一个收藏夹</strong>
      <p>视频会像 B 站一样在右侧直接铺开。</p>
    </section>

    <div v-else-if="selectedFolder.loadingVideos" class="collection-empty-panel">正在读取视频列表...</div>
    <div v-else-if="selectedFolder.videoError" class="collection-empty-panel danger-text">{{ selectedFolder.videoError }}</div>
    <section v-else-if="selectedFolder.videos.length" class="collection-video-grid">
      <article
        v-for="video in selectedFolder.videos"
        :key="video.bvid"
        class="collection-video-card"
        :class="[
          videoTone(video),
          {
            active: selectedVideo?.bvid === video.bvid && !video.is_invalid,
            invalid: video.is_invalid,
          },
        ]"
      >
        <button class="collection-video-cover" type="button" :disabled="video.is_invalid" @click="store.selectVideo(selectedFolder, video)">
          <img
            v-if="video.cover_url && !video.coverLoadFailed"
            :src="video.cover_url"
            :alt="video.title"
            loading="lazy"
            referrerpolicy="no-referrer"
            @error="video.coverLoadFailed = true"
          />
          <span v-else>{{ video.is_invalid ? "失效视频" : "暂无封面" }}</span>
        </button>

        <div class="collection-video-copy">
          <div class="collection-video-top">
            <span class="collection-video-state">{{ video.is_invalid ? "已失效" : syncStatusLabel(video.sync_status) }}</span>
            <button v-if="video.watch_url" class="ghost-button small" type="button" @click="openVideoLink(video)">打开</button>
          </div>
          <button class="collection-video-title" type="button" :disabled="video.is_invalid" @click="store.selectVideo(selectedFolder, video)">
            {{ video.title }}
          </button>
          <div class="collection-video-meta">
            <span>{{ formatDuration(video.duration) }}</span>
            <span>{{ video.up_name || "未知 UP" }}</span>
            <span>片段 {{ video.chunk_count || 0 }}</span>
          </div>
        </div>

        <div v-if="selectedVideo?.bvid === video.bvid && !video.is_invalid" class="collection-video-actions">
          <button type="button" :disabled="video.processBusy || video.sync_status === 'indexed'" @click="handleProcess(video)">
            {{ video.processBusy ? "处理中..." : (video.processActionLabel || "处理") }}
          </button>
          <button class="ghost-button" type="button" :disabled="video.resetBusy" @click="handleReset(video)">
            {{ video.resetBusy ? "重置中" : "重置" }}
          </button>
          <button
            class="ghost-button"
            type="button"
            :disabled="!(canOpenSummary(video) || canGenerateSummary(video))"
            @click="handleSummary(video)"
          >
            {{ video.summaryBusy ? "生成中" : (video.has_summary ? "摘要" : "生成摘要") }}
          </button>
          <button
            class="ghost-button"
            type="button"
            :disabled="!canOpenTranscript(video)"
            @click="handleTranscript(video)"
          >
            转写
          </button>
        </div>
      </article>
    </section>

    <section v-else class="collection-empty-panel">
      <strong>这个收藏夹还没有视频</strong>
      <p>先同步一次，或者去搜 B 站补内容。</p>
    </section>
  </section>
</template>

<script setup>
import { storeToRefs } from "pinia";

import { useWorkspaceStore } from "@/stores/workspace";
import {
  canGenerateSummary,
  canOpenSummary,
  canOpenTranscript,
  formatDuration,
  openVideoLink,
  syncStatusLabel,
  videoTone,
} from "@/utils/video";

const store = useWorkspaceStore();
const { selectedFolder, selectedVideo } = storeToRefs(store);

async function focusVideo(video) {
  if (!selectedFolder.value || video.is_invalid) {
    return;
  }
  store.selectVideo(selectedFolder.value, video);
}

async function handleProcess(video) {
  await focusVideo(video);
  await store.processSelectedVideo();
}

async function handleReset(video) {
  await focusVideo(video);
  await store.resetSelectedVideo();
}

async function handleSummary(video) {
  await focusVideo(video);
  if (video.has_summary) {
    await store.openDocumentViewer("summary", video);
    return;
  }
  await store.generateSummary(video);
}

async function handleTranscript(video) {
  await focusVideo(video);
  await store.openDocumentViewer("transcript", video);
}
</script>

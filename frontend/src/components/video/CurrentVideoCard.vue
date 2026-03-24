<template>
  <section v-if="selectedVideo" class="side-card video-side-card">
    <div class="side-card-head">
      <div>
        <div class="side-card-label">当前视频</div>
        <h3 :title="selectedVideo.title">{{ selectedVideo.title }}</h3>
      </div>
      <span class="hero-badge" :class="videoTone(selectedVideo)">{{ selectedVideo.sync_status || "pending" }}</span>
    </div>
    <div class="video-status-actions side-actions">
      <button
        type="button"
        :disabled="selectedVideo.processBusy || selectedVideo.sync_status === 'indexed'"
        @click="store.processSelectedVideo"
      >
        {{ selectedVideo.processBusy ? "处理中..." : (selectedVideo.processActionLabel || "处理") }}
      </button>
      <button class="ghost-button" type="button" @click="store.resetSelectedVideo">重置</button>
      <button
        class="ghost-button"
        type="button"
        :disabled="!(canOpenSummary(selectedVideo) || canGenerateSummary(selectedVideo))"
        @click="selectedVideo?.has_summary ? store.openDocumentViewer('summary', selectedVideo) : store.generateSummary(selectedVideo)"
      >
        {{
          selectedVideo?.summaryBusy
            ? "生成中"
            : (selectedVideo?.has_summary ? "查看摘要" : "生成摘要")
        }}
      </button>
      <button
        class="ghost-button"
        type="button"
        :disabled="!canOpenTranscript(selectedVideo) || (documentViewerPanes.transcript.loading && documentViewerVideoBvid === selectedVideo.bvid)"
        @click="store.openDocumentViewer('transcript', selectedVideo)"
      >
        {{ documentViewerPanes.transcript.loading && documentViewerVideoBvid === selectedVideo.bvid ? "转写中" : "查看转写" }}
      </button>
    </div>
    <div class="summary-state-strip" :class="summaryStateTone(selectedVideo)">
      <span class="summary-state-dot"></span>
      <span>{{ summaryStateLabel(selectedVideo) }}</span>
    </div>
    <div class="process-checklist">
      <div v-for="step in selectedVideo.steps" :key="step.step" class="process-row" :class="step.status">
        <span class="process-row-dot"></span>
        <span class="process-row-label">{{ step.label }}</span>
        <span class="process-row-status">{{ step.status_label }}</span>
      </div>
    </div>
    <div v-if="selectedVideo?.over_limit" class="process-alert side-alert">
      超过{{ selectedVideo.max_video_minutes || processingSettings.max_video_minutes }}分钟限制，处理会被拦截。
    </div>
  </section>
</template>

<script setup>
import { storeToRefs } from "pinia";

import { useWorkspaceStore } from "@/stores/workspace";
import {
  canGenerateSummary,
  canOpenSummary,
  canOpenTranscript,
  summaryStateLabel,
  summaryStateTone,
  videoTone,
} from "@/utils/video";

const store = useWorkspaceStore();
const { documentViewerPanes, documentViewerVideoBvid, processingSettings, selectedVideo } = storeToRefs(store);
</script>

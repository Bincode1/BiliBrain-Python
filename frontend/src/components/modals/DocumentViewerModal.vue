<template>
  <div v-if="documentViewerOpen" class="modal-shell document-modal-shell" @click.self="store.closeDocumentViewer">
    <div class="modal-card document-modal">
      <div class="document-modal-head">
        <div class="document-modal-copy">
          <div class="side-card-label">当前视频资料</div>
          <h2 :title="documentViewerTitle">{{ documentViewerTitle }}</h2>
        </div>
        <button class="ghost-button small" type="button" @click="store.closeDocumentViewer">关闭</button>
      </div>
      <div class="document-mode-switch">
        <button type="button" :class="{ active: documentViewerMode === 'summary' }" @click="store.switchDocumentViewerMode('summary')">
          摘要
        </button>
        <button type="button" :class="{ active: documentViewerMode === 'transcript' }" @click="store.switchDocumentViewerMode('transcript')">
          转写
        </button>
      </div>
      <div class="document-meta-line">
        <span class="document-kind-chip" :class="documentViewerMode">{{ documentViewerMode === "summary" ? "视频摘要" : "完整转写" }}</span>
        <span v-if="activeDocumentPane.meta">{{ activeDocumentPane.meta }}</span>
      </div>
      <div v-if="activeDocumentPane.loading" class="document-empty">正在加载内容...</div>
      <div v-else-if="activeDocumentPane.error" class="document-empty danger-text">{{ activeDocumentPane.error }}</div>
      <div v-else class="document-body" :class="documentViewerMode">
        <div v-if="documentViewerMode === 'summary'" class="document-rich" v-html="renderMarkdown(activeDocumentPane.text)"></div>
        <pre v-else class="document-plain">{{ activeDocumentPane.text }}</pre>
      </div>
    </div>
  </div>
</template>

<script setup>
import { storeToRefs } from "pinia";

import { useWorkspaceStore } from "@/stores/workspace";
import { renderMarkdown } from "@/utils/chat";

const store = useWorkspaceStore();
const { activeDocumentPane, documentViewerMode, documentViewerOpen, documentViewerTitle } = storeToRefs(store);
</script>

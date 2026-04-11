import { computed, reactive, ref } from "vue";
import { defineStore } from "pinia";

import { api } from "@/services/http";
import { useFoldersStore } from "./folders";

export const useDocumentViewerStore = defineStore("documentViewer", () => {
  const documentViewerOpen = ref(false);
  const documentViewerMode = ref("summary");
  const documentViewerVideoBvid = ref("");
  const documentViewerTitle = ref("");
  const documentViewerPanes = reactive({
    summary: { loading: false, text: "", meta: "", error: "", loadedBvid: "" },
    transcript: { loading: false, text: "", meta: "", error: "", loadedBvid: "" },
  });

  const activeDocumentPane = computed(() => documentViewerPanes[documentViewerMode.value] || documentViewerPanes.summary);

  function resetDocumentPane(kind) {
    documentViewerPanes[kind].loading = false;
    documentViewerPanes[kind].text = "";
    documentViewerPanes[kind].meta = "";
    documentViewerPanes[kind].error = "";
    documentViewerPanes[kind].loadedBvid = "";
  }

  function closeDocumentViewer() {
    documentViewerOpen.value = false;
  }

  function primeDocumentViewer(video) {
    const nextBvid = String(video?.bvid || "");
    if (!nextBvid) return false;
    if (documentViewerVideoBvid.value !== nextBvid) {
      documentViewerVideoBvid.value = nextBvid;
      documentViewerTitle.value = video?.title || nextBvid;
      resetDocumentPane("summary");
      resetDocumentPane("transcript");
    } else if (!documentViewerTitle.value) {
      documentViewerTitle.value = video?.title || nextBvid;
    }
    return true;
  }

  function snapshotDocumentViewer() {
    return {
      open: documentViewerOpen.value,
      mode: documentViewerMode.value,
      videoBvid: documentViewerVideoBvid.value,
      title: documentViewerTitle.value,
      panes: {
        summary: { ...documentViewerPanes.summary },
        transcript: { ...documentViewerPanes.transcript },
      },
    };
  }

  function restoreDocumentViewer(snapshot) {
    if (!snapshot) return;
    documentViewerOpen.value = snapshot.open;
    documentViewerMode.value = snapshot.mode;
    documentViewerVideoBvid.value = snapshot.videoBvid;
    documentViewerTitle.value = snapshot.title;
    Object.assign(documentViewerPanes.summary, snapshot.panes.summary);
    Object.assign(documentViewerPanes.transcript, snapshot.panes.transcript);
  }

  async function loadDocumentPane(kind, video, options = {}) {
    const { background = false, force = false } = options;
    if (!video || !primeDocumentViewer(video)) return;
    const pane = documentViewerPanes[kind];
    if (!force && pane.loadedBvid === video.bvid && (pane.text || pane.error)) return;
    const endpoint = kind === "summary" ? "summary" : "transcript";
    try {
      if (!background) pane.loading = true;
      pane.error = "";
      const data = await api(`/api/videos/${encodeURIComponent(video.bvid)}/${endpoint}`);
      pane.meta =
        kind === "summary"
          ? `摘要已整理 · 更新时间 ${data.updated_at || "未知"}`
          : `来源：${data.transcript_source} · 分段 ${data.segment_count} 个 · 更新时间 ${data.updated_at || "未知"}`;
      pane.text = data.text || (kind === "summary" ? "没有可显示的摘要内容。" : "没有可显示的转写文本。");
      pane.loadedBvid = video.bvid;
      documentViewerOpen.value = true;
    } catch (error) {
      if (!background) {
        pane.meta = "";
        pane.text = "";
        pane.error = error.message;
        pane.loadedBvid = video.bvid;
        documentViewerOpen.value = true;
      }
    } finally {
      if (!background) pane.loading = false;
    }
  }

  async function openDocumentViewer(kind, video) {
    if (!video) return;
    documentViewerMode.value = kind;
    documentViewerOpen.value = true;
    await loadDocumentPane(kind, video);
  }

  async function switchDocumentViewerMode(kind) {
    documentViewerMode.value = kind;
    const foldersStore = useFoldersStore();
    const video = foldersStore.findVideoByBvid(documentViewerVideoBvid.value) || foldersStore.selectedVideo;
    if (video) {
      await loadDocumentPane(kind, video);
    }
  }

  return {
    documentViewerOpen,
    documentViewerMode,
    documentViewerVideoBvid,
    documentViewerTitle,
    documentViewerPanes,
    activeDocumentPane,
    resetDocumentPane,
    closeDocumentViewer,
    primeDocumentViewer,
    snapshotDocumentViewer,
    restoreDocumentViewer,
    loadDocumentPane,
    openDocumentViewer,
    switchDocumentViewerMode,
  };
});

import { computed, reactive, ref, watch } from "vue";
import { defineStore } from "pinia";

import { clearStatus, createStatus, setStatus } from "@/composables/useStatus";
import { api } from "@/services/http";
import {
  applyProcessStatus,
  canGenerateSummary,
  decorateFolder,
  decorateVideo,
  firstSelectableVideo,
  hasTranscript,
  resetVideoProcessState,
} from "@/utils/video";

import { useAuthStore } from "./auth";
import { useChatStore } from "./chat";
import { useDialogStore } from "./dialog";
import { useDocumentViewerStore } from "./documentViewer";
import { useFolderSearchStore } from "./folderSearch";

const STORAGE_KEY = "bilibrain_workspace_state";

export const useFoldersStore = defineStore("folders", () => {
  const syncStatus = createStatus();
  const settingsStatus = createStatus();
  const folders = ref([]);
  const selectedFolderId = ref("");
  const selectedVideoBvid = ref("");
  const processingSettings = reactive({ max_video_minutes: 30, saving: false });
  const processPollers = new Map();

  // --- localStorage persistence ---
  function loadPersistedState() {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      if (saved) {
        const state = JSON.parse(saved);
        if (state.selectedFolderId) selectedFolderId.value = state.selectedFolderId;
        if (state.selectedVideoBvid) selectedVideoBvid.value = state.selectedVideoBvid;
      }
    } catch {
      // ignore parse errors
    }
  }

  function savePersistedState() {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      const state = saved ? JSON.parse(saved) : {};
      state.selectedFolderId = selectedFolderId.value;
      state.selectedVideoBvid = selectedVideoBvid.value;
      localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
    } catch {
      // ignore storage errors
    }
  }

  watch(selectedFolderId, savePersistedState);
  watch(selectedVideoBvid, savePersistedState);
  loadPersistedState();

  // --- Computed ---
  const selectedFolder = computed(() =>
    folders.value.find((folder) => String(folder.folder_id) === String(selectedFolderId.value)) || null
  );
  const selectedVideo = computed(() =>
    selectedFolder.value?.videos.find((video) => video.bvid === selectedVideoBvid.value) || null
  );

  // --- Helpers ---
  function findFolder(folderId) {
    return folders.value.find((folder) => String(folder.folder_id) === String(folderId)) || null;
  }

  function findVideo(folderId, bvid) {
    return findFolder(folderId)?.videos.find((video) => video.bvid === bvid) || null;
  }

  function findVideoByBvid(bvid) {
    for (const folder of folders.value) {
      if (!folder.videos) continue;
      const video = folder.videos.find((item) => item.bvid === bvid);
      if (video) return video;
    }
    return null;
  }

  function syncSelectedVideoForFolder(folder) {
    if (!folder) {
      selectedVideoBvid.value = "";
      return;
    }
    const currentVideoExists = folder.videos.some(
      (video) => video.bvid === selectedVideoBvid.value && !video.is_invalid
    );
    if (currentVideoExists) return;
    const selectable = firstSelectableVideo(folder.videos);
    selectedVideoBvid.value = selectable ? selectable.bvid : "";
  }

  function snapshotVideoState(video) {
    return {
      ...video,
      manual_tags: Array.isArray(video.manual_tags) ? [...video.manual_tags] : [],
      steps: Array.isArray(video.steps) ? video.steps.map((step) => ({ ...step })) : [],
    };
  }

  function restoreVideoState(video, snapshot) {
    Object.assign(video, {
      ...snapshot,
      manual_tags: Array.isArray(snapshot.manual_tags) ? [...snapshot.manual_tags] : [],
      steps: Array.isArray(snapshot.steps) ? snapshot.steps.map((step) => ({ ...step })) : [],
    });
  }

  function parseTagInput(raw) {
    return String(raw || "")
      .split(/[,，\n]+/)
      .map((item) => item.trim())
      .filter(Boolean);
  }

  // --- Poller management ---
  function stopProcessPoller(bvid) {
    const timer = processPollers.get(bvid);
    if (timer) {
      clearInterval(timer);
      processPollers.delete(bvid);
    }
  }

  function stopAllPollers() {
    processPollers.forEach((timer) => clearInterval(timer));
    processPollers.clear();
  }

  function clearVideoArtifactsLocally(video) {
    stopProcessPoller(video.bvid);
    resetVideoProcessState(video, processingSettings.max_video_minutes);
    const docStore = useDocumentViewerStore();
    if (docStore.documentViewerVideoBvid === video.bvid) {
      docStore.closeDocumentViewer();
      docStore.resetDocumentPane("summary");
      docStore.resetDocumentPane("transcript");
      docStore.documentViewerVideoBvid = "";
      docStore.documentViewerTitle = "";
    }
  }

  // --- Settings ---
  async function loadSettings() {
    const data = await api("/api/settings");
    processingSettings.max_video_minutes = Number(data.max_video_minutes || 30);
  }

  async function saveSettings() {
    try {
      clearStatus(settingsStatus);
      processingSettings.saving = true;
      const data = await api("/api/settings", {
        method: "POST",
        body: JSON.stringify({ max_video_minutes: Number(processingSettings.max_video_minutes || 30) }),
      });
      processingSettings.max_video_minutes = Number(data.max_video_minutes || 30);
      setStatus(settingsStatus, `已保存全局时长限制：${processingSettings.max_video_minutes} 分钟`);
    } catch (error) {
      setStatus(settingsStatus, error.message, true);
    } finally {
      processingSettings.saving = false;
    }
  }

  async function resetAllProcessedContent() {
    const dialogStore = useDialogStore();
    const docStore = useDocumentViewerStore();

    const confirmed = await dialogStore.confirmDialog({
      title: "重置全部已处理内容",
      message: "这会清空所有已转写、已摘要和已入库内容，但会保留音频缓存、收藏夹和视频元数据。",
      confirmLabel: "确认重置",
      cancelLabel: "取消",
      tone: "danger",
    });
    if (!confirmed) return;

    try {
      clearStatus(syncStatus);
      setStatus(syncStatus, "正在重置所有已加载内容...");
      docStore.closeDocumentViewer();
      docStore.resetDocumentPane("summary");
      docStore.resetDocumentPane("transcript");
      docStore.documentViewerVideoBvid = "";
      docStore.documentViewerTitle = "";
      const data = await api("/api/videos/reset-all", { method: "POST" });
      await loadFolders();
      if (selectedFolderId.value) {
        const folder = findFolder(selectedFolderId.value);
        if (folder) await openFolder(folder, true);
      }
      setStatus(syncStatus, `重置完成：${Number(data.video_count || 0)} 个视频的处理结果已清空，音频缓存已保留。`);
    } catch (error) {
      setStatus(syncStatus, error.message, true);
    }
  }

  // --- Folders ---
  async function loadFolders() {
    clearStatus(syncStatus);
    stopAllPollers();
    const authStore = useAuthStore();
    const searchStore = useFolderSearchStore();

    try {
      if (!authStore.session.loggedIn) {
        folders.value = [];
        searchStore.closeFolderSearch();
        return;
      }
      const query = authStore.session.uid ? `?uid=${encodeURIComponent(authStore.session.uid)}` : "";
      const data = await api(`/api/folders${query}`);
      folders.value = (data.folders || []).map(decorateFolder);
      setStatus(syncStatus, `已读取 ${folders.value.length} 个收藏夹。`);

      const folderExists = (id) => folders.value.some((folder) => String(folder.folder_id) === String(id));
      if (searchStore.folderSearchFolderId && !folderExists(searchStore.folderSearchFolderId)) {
        searchStore.closeFolderSearch();
      }

      // 通知 chat store 校验 scope
      const chatStore = useChatStore();
      if (chatStore.chatScopeFolderId && !folderExists(chatStore.chatScopeFolderId)) {
        chatStore.chatScopeFolderId = "";
        chatStore.chatScopeVideoBvid = "";
      }
      if (!chatStore.chatScopeFolderId && folders.value.length) {
        chatStore.chatScopeFolderId = String(folders.value[0].folder_id);
      }

      if (selectedFolderId.value && !folderExists(selectedFolderId.value)) {
        selectedFolderId.value = "";
        selectedVideoBvid.value = "";
      }
      if (selectedFolderId.value && folderExists(selectedFolderId.value)) {
        const folder = folders.value.find((f) => String(f.folder_id) === String(selectedFolderId.value));
        if (folder) {
          const videoExists = folder.videos.some((v) => v.bvid === selectedVideoBvid.value);
          if (!videoExists) selectedVideoBvid.value = "";
          await openFolder(folder, true);
        }
      }
      if (!selectedFolderId.value && folders.value.length) {
        await openFolder(folders.value[0], true).catch((error) => {
          setStatus(syncStatus, error.message, true);
        });
      }
      if (chatStore.chatScopeFolderId) {
        await chatStore.ensureChatScopeSelection(chatStore.chatScopeFolderId, {
          loadVideos: true,
          autoSelectVideo: chatStore.chatScopeMode === "video",
        });
      }
    } catch (error) {
      setStatus(syncStatus, error.message, true);
    }
  }

  async function ensureFolderVideos(folder, options = {}) {
    const { force = false } = options;
    if (!folder) return [];
    if (folder.videos.length && !force) return folder.videos;
    folder.loadingVideos = true;
    folder.videoError = "";
    try {
      const data = await api(`/api/folders/${folder.folder_id}/videos`);
      folder.fields = data.fields || [];
      folder.videos = (data.videos || []).map(decorateVideo);
      return folder.videos;
    } catch (error) {
      folder.videoError = error.message;
      throw error;
    } finally {
      folder.loadingVideos = false;
    }
  }

  async function openFolder(folder, force = false) {
    folder.expanded = true;
    selectedFolderId.value = String(folder.folder_id);
    if (folder.videos.length && !force) {
      syncSelectedVideoForFolder(folder);
      return;
    }
    try {
      await ensureFolderVideos(folder, { force });
      syncSelectedVideoForFolder(folder);
    } catch (error) {
      folder.videoError = error.message;
    }
  }

  function selectVideo(folder, video) {
    if (video.is_invalid) return;
    selectedFolderId.value = String(folder.folder_id);
    selectedVideoBvid.value = video.bvid;
  }

  async function syncFolder(folder) {
    clearStatus(syncStatus);
    setStatus(syncStatus, `正在同步「${folder.title}」...`);
    try {
      const data = await api("/api/sync", {
        method: "POST",
        body: JSON.stringify({ folder_id: folder.folder_id }),
      });
      const previousSelected = selectedFolderId.value;
      await loadFolders();
      setStatus(syncStatus, data.logs?.join(" ") || "同步完成。");
      if (previousSelected) {
        const sameFolder = findFolder(previousSelected);
        if (sameFolder) await openFolder(sameFolder, true);
      }
    } catch (error) {
      setStatus(syncStatus, error.message, true);
    }
  }

  // --- Video processing ---
  function startProcessPoller(folderId, bvid) {
    stopProcessPoller(bvid);
    let prevSignature = null;
    let prevOperation = null;
    const docStore = useDocumentViewerStore();
    const chatStore = useChatStore();

    const timer = setInterval(async () => {
      try {
        const data = await api(`/api/videos/${encodeURIComponent(bvid)}/process/status`);
        const video = findVideo(folderId, bvid);
        if (!video) {
          stopProcessPoller(bvid);
          return;
        }
        const signature = JSON.stringify({
          running: Boolean(data.running),
          operation: data.operation || "",
          queueStatus: data.queue_status || "",
          resetStatus: data.reset_status || "",
          overallStatus: data.overall_status || "",
          errorMsg: data.error_msg || "",
          chunkCount: Number(data.chunk_count || 0),
          transcriptSegments: Number(data.transcript_segment_count || 0),
          hasSummary: Boolean(data.has_summary),
        });
        if (signature !== prevSignature) {
          prevSignature = signature;
          applyProcessStatus(video, data, processingSettings.max_video_minutes);
        }
        prevOperation = data.operation || prevOperation;
        if (!data.running) {
          stopProcessPoller(bvid);
          video.processBusy = false;
          video.resetBusy = false;
          if (prevOperation === "reset") {
            if (data.reset_status === "failed" && data.error_msg) {
              chatStore.setChatStatus(data.error_msg, true);
            } else {
              chatStore.clearChatStatus();
            }
          }
          if (docStore.documentViewerOpen && docStore.documentViewerVideoBvid === video.bvid) {
            if (docStore.documentViewerPanes.transcript.loadedBvid === video.bvid && data.has_transcript) {
              await docStore.loadDocumentPane("transcript", video, { background: true, force: true });
            }
            if ((docStore.documentViewerPanes.summary.loadedBvid === video.bvid || data.has_summary) && hasTranscript(video)) {
              await docStore.loadDocumentPane("summary", video, { background: true, force: true });
            }
          }
        }
      } catch {
        stopProcessPoller(bvid);
        const video = findVideo(folderId, bvid);
        if (video) {
          video.processBusy = false;
          video.resetBusy = false;
        }
      }
    }, 2000);
    processPollers.set(bvid, timer);
  }

  async function processSelectedVideo() {
    const folder = selectedFolder.value;
    const video = selectedVideo.value;
    if (!folder || !video || video.processBusy || video.resetBusy || video.sync_status === "indexed") return;
    const chatStore = useChatStore();
    try {
      video.processBusy = true;
      const data = await api(`/api/videos/${encodeURIComponent(video.bvid)}/process`, { method: "POST" });
      applyProcessStatus(video, data, processingSettings.max_video_minutes);
      if (data.started || data.running) {
        startProcessPoller(folder.folder_id, video.bvid);
      } else {
        video.processBusy = false;
      }
    } catch (error) {
      video.processBusy = false;
      chatStore.setChatStatus(error.message, true);
    }
  }

  async function resetSelectedVideo() {
    const folder = selectedFolder.value;
    const video = selectedVideo.value;
    if (!folder || !video || video.resetBusy) return;
    const docStore = useDocumentViewerStore();
    const chatStore = useChatStore();

    const videoSnapshot = snapshotVideoState(video);
    const viewerSnapshot = docStore.documentViewerVideoBvid === video.bvid ? docStore.snapshotDocumentViewer() : null;
    video.resetBusy = true;
    chatStore.clearChatStatus();
    clearVideoArtifactsLocally(video);
    try {
      chatStore.setChatStatus("正在重置当前视频...");
      const data = await api(`/api/videos/${encodeURIComponent(video.bvid)}/reset`, { method: "POST" });
      applyProcessStatus(video, data, processingSettings.max_video_minutes);
      if (data.started || data.running || data.reset_running) {
        startProcessPoller(folder.folder_id, video.bvid);
      } else {
        chatStore.clearChatStatus();
      }
    } catch (error) {
      restoreVideoState(video, videoSnapshot);
      docStore.restoreDocumentViewer(viewerSnapshot);
      video.resetBusy = false;
      chatStore.setChatStatus(error.message, true);
    }
  }

  async function saveSelectedVideoTags() {
    const video = selectedVideo.value;
    if (!video) return;
    const chatStore = useChatStore();
    try {
      const tags = parseTagInput(video.manualTagsInput);
      const data = await api(`/api/videos/${encodeURIComponent(video.bvid)}/tags`, {
        method: "POST",
        body: JSON.stringify({ tags }),
      });
      video.manual_tags = data.manual_tags || [];
      video.manualTagsInput = video.manual_tags.join(", ");
    } catch (error) {
      chatStore.setChatStatus(error.message, true);
    }
  }

  async function generateSummary(video, options = {}) {
    const { openViewer = true } = options;
    if (!canGenerateSummary(video)) return;
    const docStore = useDocumentViewerStore();
    const chatStore = useChatStore();

    chatStore.clearChatStatus();
    video.summaryBusy = true;
    try {
      const data = await api(`/api/videos/${encodeURIComponent(video.bvid)}/summary`, {
        method: "POST",
        timeoutMs: 180_000,
      });
      video.has_summary = true;
      video.summary_updated_at = data.updated_at || "";
      if (openViewer) {
        docStore.documentViewerMode = "summary";
        docStore.primeDocumentViewer(video);
        docStore.documentViewerOpen = true;
      }
      docStore.documentViewerPanes.summary.text = data.text || "";
      docStore.documentViewerPanes.summary.meta = `摘要已整理 · 更新时间 ${data.updated_at || "未知"}`;
      docStore.documentViewerPanes.summary.error = "";
      docStore.documentViewerPanes.summary.loadedBvid = video.bvid;
    } catch (error) {
      chatStore.setChatStatus(error.message, true);
    } finally {
      video.summaryBusy = false;
    }
  }

  function cleanup() {
    stopAllPollers();
  }

  return {
    syncStatus,
    settingsStatus,
    folders,
    selectedFolderId,
    selectedVideoBvid,
    processingSettings,
    selectedFolder,
    selectedVideo,
    findFolder,
    findVideo,
    findVideoByBvid,
    syncSelectedVideoForFolder,
    snapshotVideoState,
    restoreVideoState,
    stopProcessPoller,
    stopAllPollers,
    clearVideoArtifactsLocally,
    loadSettings,
    saveSettings,
    resetAllProcessedContent,
    loadFolders,
    ensureFolderVideos,
    openFolder,
    selectVideo,
    syncFolder,
    startProcessPoller,
    processSelectedVideo,
    resetSelectedVideo,
    saveSelectedVideoTags,
    generateSummary,
    cleanup,
  };
});

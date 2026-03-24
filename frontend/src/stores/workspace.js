import { computed, nextTick, reactive, ref, watch } from "vue";
import { defineStore } from "pinia";

import { clearStatus, createStatus, setStatus } from "@/composables/useStatus";
import { api } from "@/services/http";
import {
  normalizeChatMessage,
  normalizeConversation,
} from "@/utils/chat";
import { parseSseEvent, parseSseFrames } from "@/utils/sse";
import {
  applyProcessStatus,
  canGenerateSummary,
  decorateFolder,
  decorateVideo,
  firstSelectableVideo,
  hasTranscript,
} from "@/utils/video";

export const useWorkspaceStore = defineStore("workspace", () => {
  const sessionStatus = createStatus();
  const syncStatus = createStatus();
  const chatStatus = createStatus();
  const qrStatus = createStatus();
  const settingsStatus = createStatus();

  const qrSvg = ref("");
  const qrModalOpen = ref(false);
  const folders = ref([]);
  const selectedFolderId = ref("");
  const selectedVideoBvid = ref("");
  const chatInput = ref("");
  const chatScopeMode = ref("video");
  const chatScopeFolderId = ref("");
  const activeConversationId = ref(null);
  const chatConversations = ref([]);
  const chatMessages = ref([]);
  const chatHistoryLoading = ref(false);
  const chatConversationsLoading = ref(false);
  const deletingConversationId = ref(null);
  const processingSettings = reactive({
    max_video_minutes: 30,
    saving: false,
  });
  const session = reactive({
    loggedIn: false,
    userName: "",
    uid: "",
  });
  const documentViewerOpen = ref(false);
  const documentViewerMode = ref("summary");
  const documentViewerVideoBvid = ref("");
  const documentViewerTitle = ref("");
  const documentViewerPanes = reactive({
    summary: { loading: false, text: "", meta: "", error: "", loadedBvid: "" },
    transcript: { loading: false, text: "", meta: "", error: "", loadedBvid: "" },
  });

  let qrPollTimer = null;
  const processPollers = new Map();
  let chatStreamEl = null;

  const selectedFolder = computed(() => folders.value.find((folder) => String(folder.folder_id) === String(selectedFolderId.value)) || null);
  const selectedVideo = computed(() => selectedFolder.value?.videos.find((video) => video.bvid === selectedVideoBvid.value) || null);
  const selectedChatFolder = computed(() => folders.value.find((folder) => String(folder.folder_id) === String(chatScopeFolderId.value)) || null);
  const selectedConversation = computed(() =>
    chatConversations.value.find((item) => Number(item.conversation_id) === Number(activeConversationId.value)) || null
  );
  const activeDocumentPane = computed(() => documentViewerPanes[documentViewerMode.value] || documentViewerPanes.summary);
  const chatPlaceholder = computed(() => {
    if (chatScopeMode.value === "video") {
      return "例如：总结一下这个视频的核心要点，或者问某个细节。";
    }
    if (chatScopeMode.value === "folder") {
      return "例如：请帮我梳理这个收藏夹里 Django 的学习路线。";
    }
    return "例如：哪些已入库视频提到 LangGraph，或者整体都在讲什么？";
  });

  function setChatStreamEl(element) {
    chatStreamEl = element || null;
  }

  function scrollChatToBottom() {
    nextTick(() => {
      if (!chatStreamEl) {
        return;
      }
      chatStreamEl.scrollTop = chatStreamEl.scrollHeight;
    });
  }

  function toggleMessageSources(message) {
    message.sourcesExpanded = !message.sourcesExpanded;
  }

  function findFolder(folderId) {
    return folders.value.find((folder) => String(folder.folder_id) === String(folderId)) || null;
  }

  function findVideo(folderId, bvid) {
    return findFolder(folderId)?.videos.find((video) => video.bvid === bvid) || null;
  }

  function findVideoByBvid(bvid) {
    for (const folder of folders.value) {
      const video = (folder.videos || []).find((item) => item.bvid === bvid);
      if (video) {
        return video;
      }
    }
    return null;
  }

  function stopProcessPoller(bvid) {
    const timer = processPollers.get(bvid);
    if (timer) {
      clearInterval(timer);
      processPollers.delete(bvid);
    }
  }

  function stopAllPollers() {
    for (const bvid of processPollers.keys()) {
      stopProcessPoller(bvid);
    }
  }

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

  function closeQrModal() {
    qrModalOpen.value = false;
    qrSvg.value = "";
    clearStatus(qrStatus);
    if (qrPollTimer) {
      clearInterval(qrPollTimer);
      qrPollTimer = null;
    }
  }

  function primeDocumentViewer(video) {
    const nextBvid = String(video?.bvid || "");
    if (!nextBvid) {
      return false;
    }
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

  function parseTagInput(raw) {
    return String(raw || "")
      .split(/[,，\n]+/)
      .map((item) => item.trim())
      .filter(Boolean);
  }

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
    if (!window.confirm("这会清空所有已转写、已入库和音频缓存内容，但会保留收藏夹和视频元数据。确定继续吗？")) {
      return;
    }

    try {
      clearStatus(syncStatus);
      setStatus(syncStatus, "正在重置所有已加载内容...");
      closeDocumentViewer();
      resetDocumentPane("summary");
      resetDocumentPane("transcript");
      documentViewerVideoBvid.value = "";
      documentViewerTitle.value = "";
      const data = await api("/api/videos/reset-all", { method: "POST" });
      await loadFolders();
      if (selectedFolderId.value) {
        const folder = findFolder(selectedFolderId.value);
        if (folder) {
          await openFolder(folder, true);
        }
      }
      setStatus(
        syncStatus,
        `重置完成：${Number(data.video_count || 0)} 个视频，${Number(data.audio_file_count || 0)} 个音频缓存已清除。`
      );
    } catch (error) {
      setStatus(syncStatus, error.message, true);
    }
  }

  async function refreshSession() {
    try {
      const data = await api("/api/auth/session");
      if (data.logged_in) {
        session.loggedIn = true;
        session.userName = data.user_name || "";
        session.uid = data.uid ? String(data.uid) : "";
        setStatus(sessionStatus, `已登录：${data.user_name}（UID ${data.uid}）`);
      } else {
        session.loggedIn = false;
        session.userName = "";
        session.uid = "";
        folders.value = [];
        chatScopeFolderId.value = "";
        activeConversationId.value = null;
        chatConversations.value = [];
        chatMessages.value = [];
        setStatus(sessionStatus, "当前未登录。", true);
      }
    } catch (error) {
      session.loggedIn = false;
      session.userName = "";
      session.uid = "";
      folders.value = [];
      chatScopeFolderId.value = "";
      activeConversationId.value = null;
      chatConversations.value = [];
      chatMessages.value = [];
      setStatus(sessionStatus, error.message, true);
    }
  }

  async function startQrLogin() {
    clearStatus(sessionStatus);
    clearStatus(qrStatus);
    qrModalOpen.value = true;
    try {
      const data = await api("/api/auth/qr/start", { method: "POST" });
      qrSvg.value = data.svg;
      setStatus(qrStatus, "请打开 Bilibili App 扫码。");
      if (qrPollTimer) {
        clearInterval(qrPollTimer);
      }
      qrPollTimer = setInterval(async () => {
        try {
          const result = await api(`/api/auth/qr/poll?qrcode_key=${encodeURIComponent(data.qrcode_key)}`);
          if (result.status === "pending") {
            setStatus(qrStatus, "等待扫码。");
          } else if (result.status === "scanned") {
            setStatus(qrStatus, "已扫码，请在手机端确认。");
          } else if (result.status === "confirmed") {
            clearInterval(qrPollTimer);
            qrPollTimer = null;
            setStatus(qrStatus, "验证完成，正在刷新页面…");
            setStatus(sessionStatus, `已登录：${result.user_name}（UID ${result.uid}）`);
            closeQrModal();
            window.setTimeout(() => window.location.reload(), 500);
          } else {
            clearInterval(qrPollTimer);
            qrPollTimer = null;
            setStatus(qrStatus, result.message || "扫码失败", true);
          }
        } catch (error) {
          clearInterval(qrPollTimer);
          qrPollTimer = null;
          setStatus(qrStatus, error.message, true);
        }
      }, 2000);
    } catch (error) {
      setStatus(qrStatus, error.message, true);
    }
  }

  async function loadFolders() {
    clearStatus(syncStatus);
    stopAllPollers();
    try {
      if (!session.loggedIn) {
        folders.value = [];
        return;
      }
      const query = session.uid ? `?uid=${encodeURIComponent(session.uid)}` : "";
      const data = await api(`/api/folders${query}`);
      folders.value = (data.folders || []).map(decorateFolder);
      setStatus(syncStatus, `已读取 ${folders.value.length} 个收藏夹。`);
      if (chatScopeFolderId.value && !folders.value.some((folder) => String(folder.folder_id) === String(chatScopeFolderId.value))) {
        chatScopeFolderId.value = "";
      }
      if (!chatScopeFolderId.value && folders.value.length) {
        chatScopeFolderId.value = String(folders.value[0].folder_id);
      }
      if (!selectedFolderId.value && folders.value.length) {
        openFolder(folders.value[0], true).catch((error) => {
          setStatus(syncStatus, error.message, true);
        });
      }
    } catch (error) {
      setStatus(syncStatus, error.message, true);
    }
  }

  async function loadChatHistory(options = {}) {
    const {
      showLoading = true,
      scrollToBottomOnLoad = true,
    } = options;

    if (!session.loggedIn) {
      activeConversationId.value = null;
      chatConversations.value = [];
      chatMessages.value = [];
      return;
    }

    if (showLoading) {
      chatHistoryLoading.value = true;
    }
    try {
      const params = new URLSearchParams();
      if (activeConversationId.value) {
        params.set("conversation_id", String(activeConversationId.value));
      }
      const query = params.size ? `?${params.toString()}` : "";
      const data = await api(`/api/chat/history${query}`);
      activeConversationId.value = data.conversation_id || null;
      chatMessages.value = Array.isArray(data.messages)
        ? data.messages.map((message) => normalizeChatMessage(message, activeConversationId.value))
        : [];
    } catch (error) {
      activeConversationId.value = null;
      chatMessages.value = [];
      setStatus(chatStatus, error.message, true);
    } finally {
      if (showLoading) {
        chatHistoryLoading.value = false;
      }
    }

    if (scrollToBottomOnLoad) {
      await nextTick();
      scrollChatToBottom();
    }
  }

  async function loadChatConversations(preferredConversationId = null, options = {}) {
    const {
      historyShowLoading = true,
      historyScrollToBottomOnLoad = true,
    } = options;

    if (!session.loggedIn) {
      activeConversationId.value = null;
      chatConversations.value = [];
      chatMessages.value = [];
      return;
    }

    chatConversationsLoading.value = true;
    try {
      const data = await api("/api/chat/conversations");
      chatConversations.value = Array.isArray(data.conversations)
        ? data.conversations.map(normalizeConversation)
        : [];

      const preferredId = preferredConversationId ?? activeConversationId.value ?? data.active_conversation_id ?? null;
      const exists = chatConversations.value.some((item) => Number(item.conversation_id) === Number(preferredId));
      activeConversationId.value = exists ? Number(preferredId) : (chatConversations.value[0]?.conversation_id || null);
      await loadChatHistory({
        showLoading: historyShowLoading,
        scrollToBottomOnLoad: historyScrollToBottomOnLoad,
      });
    } catch (error) {
      activeConversationId.value = null;
      chatConversations.value = [];
      chatMessages.value = [];
      setStatus(chatStatus, error.message, true);
    } finally {
      chatConversationsLoading.value = false;
    }
  }

  async function createConversation() {
    clearStatus(chatStatus);
    try {
      const scopeFolderId = chatScopeMode.value === "folder" && selectedChatFolder.value
        ? Number(selectedChatFolder.value.folder_id)
        : null;
      const data = await api("/api/chat/conversations", {
        method: "POST",
        body: JSON.stringify({ folder_id: scopeFolderId }),
      });
      const conversation = normalizeConversation(data.conversation || {});
      activeConversationId.value = conversation.conversation_id;
      chatConversations.value = [conversation, ...chatConversations.value.filter((item) => item.conversation_id !== conversation.conversation_id)];
      chatMessages.value = [];
      chatInput.value = "";
      scrollChatToBottom();
    } catch (error) {
      setStatus(chatStatus, error.message, true);
    }
  }

  async function selectConversation(conversationId) {
    if (Number(activeConversationId.value) === Number(conversationId)) {
      return;
    }
    activeConversationId.value = Number(conversationId);
    clearStatus(chatStatus);
    await loadChatHistory();
  }

  async function deleteConversation(conversationId) {
    if (!conversationId) {
      return;
    }
    const conversation = chatConversations.value.find((item) => Number(item.conversation_id) === Number(conversationId));
    const label = conversation?.title || "这个会话";
    if (!window.confirm(`确定删除“${label}”吗？聊天记录会一起删除。`)) {
      return;
    }

    try {
      deletingConversationId.value = Number(conversationId);
      clearStatus(chatStatus);
      const data = await api(`/api/chat/conversations/${encodeURIComponent(conversationId)}`, {
        method: "DELETE",
      });
      chatConversations.value = Array.isArray(data.conversations)
        ? data.conversations.map(normalizeConversation)
        : [];
      activeConversationId.value = data.active_conversation_id || null;
      if (activeConversationId.value) {
        await loadChatHistory();
      } else {
        chatMessages.value = [];
      }
    } catch (error) {
      setStatus(chatStatus, error.message, true);
    } finally {
      deletingConversationId.value = null;
    }
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
        if (sameFolder) {
          await openFolder(sameFolder, true);
        }
      }
    } catch (error) {
      setStatus(syncStatus, error.message, true);
    }
  }

  async function openFolder(folder, force = false) {
    if (!force && folder.expanded) {
      folder.expanded = false;
      return;
    }
    folder.expanded = true;
    selectedFolderId.value = String(folder.folder_id);
    if (folder.videos.length && !force) {
      const selectable = firstSelectableVideo(folder.videos);
      if (!selectedVideoBvid.value && selectable) {
        selectedVideoBvid.value = selectable.bvid;
      }
      return;
    }
    folder.loadingVideos = true;
    folder.videoError = "";
    try {
      const data = await api(`/api/folders/${folder.folder_id}/videos`);
      folder.fields = data.fields || [];
      folder.videos = (data.videos || []).map(decorateVideo);
      const selectable = firstSelectableVideo(folder.videos);
      if (selectable) {
        selectedVideoBvid.value = selectable.bvid;
      }
    } catch (error) {
      folder.videoError = error.message;
    } finally {
      folder.loadingVideos = false;
    }
  }

  function selectVideo(folder, video) {
    if (video.is_invalid) {
      return;
    }
    selectedFolderId.value = String(folder.folder_id);
    selectedVideoBvid.value = video.bvid;
  }

  async function loadDocumentPane(kind, video, options = {}) {
    const { background = false, force = false } = options;
    if (!video || !primeDocumentViewer(video)) {
      return;
    }
    const pane = documentViewerPanes[kind];
    if (!force && pane.loadedBvid === video.bvid && (pane.text || pane.error)) {
      return;
    }
    const endpoint = kind === "summary" ? "summary" : "transcript";
    try {
      if (!background) {
        pane.loading = true;
      }
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
      if (!background) {
        pane.loading = false;
      }
    }
  }

  async function openDocumentViewer(kind, video) {
    if (!video) {
      return;
    }
    documentViewerMode.value = kind;
    documentViewerOpen.value = true;
    await loadDocumentPane(kind, video);
  }

  async function switchDocumentViewerMode(kind) {
    documentViewerMode.value = kind;
    const video = findVideoByBvid(documentViewerVideoBvid.value) || selectedVideo.value;
    if (video) {
      await loadDocumentPane(kind, video);
    }
  }

  async function generateSummary(video, options = {}) {
    const { openViewer = true } = options;
    if (!canGenerateSummary(video)) {
      return;
    }
    clearStatus(chatStatus);
    video.summaryBusy = true;
    try {
      const data = await api(`/api/videos/${encodeURIComponent(video.bvid)}/summary`, {
        method: "POST",
      });
      video.has_summary = true;
      video.summary_updated_at = data.updated_at || "";
      if (openViewer) {
        documentViewerMode.value = "summary";
        primeDocumentViewer(video);
        documentViewerOpen.value = true;
      }
      documentViewerPanes.summary.text = data.text || "";
      documentViewerPanes.summary.meta = `摘要已整理 · 更新时间 ${data.updated_at || "未知"}`;
      documentViewerPanes.summary.error = "";
      documentViewerPanes.summary.loadedBvid = video.bvid;
    } catch (error) {
      setStatus(chatStatus, error.message, true);
    } finally {
      video.summaryBusy = false;
    }
  }

  function startProcessPoller(folderId, bvid) {
    stopProcessPoller(bvid);
    const timer = setInterval(async () => {
      try {
        const data = await api(`/api/videos/${encodeURIComponent(bvid)}/process/status`);
        const video = findVideo(folderId, bvid);
        if (!video) {
          stopProcessPoller(bvid);
          return;
        }
        applyProcessStatus(video, data, processingSettings.max_video_minutes);
        if (!data.running) {
          stopProcessPoller(bvid);
          video.processBusy = false;
          if (documentViewerOpen.value && documentViewerVideoBvid.value === video.bvid) {
            if (documentViewerPanes.transcript.loadedBvid === video.bvid && data.has_transcript) {
              await loadDocumentPane("transcript", video, { background: true, force: true });
            }
            if ((documentViewerPanes.summary.loadedBvid === video.bvid || data.has_summary) && hasTranscript(video)) {
              await loadDocumentPane("summary", video, { background: true, force: true });
            }
          }
        }
      } catch {
        stopProcessPoller(bvid);
        const video = findVideo(folderId, bvid);
        if (video) {
          video.processBusy = false;
        }
      }
    }, 2000);
    processPollers.set(bvid, timer);
  }

  async function processSelectedVideo() {
    const folder = selectedFolder.value;
    const video = selectedVideo.value;
    if (!folder || !video) {
      return;
    }
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
      setStatus(chatStatus, error.message, true);
    }
  }

  async function resetSelectedVideo() {
    const video = selectedVideo.value;
    if (!video) {
      return;
    }
    try {
      const data = await api(`/api/videos/${encodeURIComponent(video.bvid)}/reset`, { method: "POST" });
      applyProcessStatus(video, data, processingSettings.max_video_minutes);
      if (documentViewerVideoBvid.value === video.bvid) {
        closeDocumentViewer();
        resetDocumentPane("summary");
        resetDocumentPane("transcript");
        documentViewerVideoBvid.value = "";
        documentViewerTitle.value = "";
      }
    } catch (error) {
      setStatus(chatStatus, error.message, true);
    }
  }

  async function saveSelectedVideoTags() {
    const video = selectedVideo.value;
    if (!video) {
      return;
    }
    try {
      const tags = parseTagInput(video.manualTagsInput);
      const data = await api(`/api/videos/${encodeURIComponent(video.bvid)}/tags`, {
        method: "POST",
        body: JSON.stringify({ tags }),
      });
      video.manual_tags = data.manual_tags || [];
      video.manualTagsInput = video.manual_tags.join(", ");
    } catch (error) {
      setStatus(chatStatus, error.message, true);
    }
  }

  async function askQuestion() {
    clearStatus(chatStatus);
    const query = chatInput.value.trim();
    if (!query) {
      setStatus(chatStatus, "请先输入问题。", true);
      return;
    }

    let scopeFolderId = null;
    let scopeBvid = null;
    if (chatScopeMode.value === "video") {
      if (!selectedVideo.value) {
        setStatus(chatStatus, "请先在左侧选中一个视频，或切换到收藏夹 / 全部范围。", true);
        return;
      }
      scopeFolderId = selectedFolder.value ? Number(selectedFolder.value.folder_id) : null;
      scopeBvid = selectedVideo.value.bvid;
    } else if (chatScopeMode.value === "folder") {
      if (!selectedChatFolder.value) {
        setStatus(chatStatus, "请先选择一个收藏夹，或切换到其他范围。", true);
        return;
      }
      scopeFolderId = Number(selectedChatFolder.value.folder_id);
    }

    const assistantMessage = reactive(normalizeChatMessage({ role: "assistant", text: "", sources: [] }, activeConversationId.value));
    chatMessages.value.push(normalizeChatMessage({ role: "user", text: query }, activeConversationId.value));
    chatMessages.value.push(assistantMessage);
    chatInput.value = "";
    scrollChatToBottom();

    try {
      const response = await fetch("/api/ask/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          query,
          folder_id: scopeFolderId,
          bvid: scopeBvid,
          scope_mode: chatScopeMode.value,
          conversation_id: activeConversationId.value,
        }),
      });
      const dataType = response.headers.get("content-type") || "";
      if (!response.ok || !dataType.includes("text/event-stream")) {
        const raw = await response.text();
        throw new Error(raw || "问答请求失败");
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let answerStarted = false;

      while (true) {
        const { value, done } = await reader.read();
        if (done) {
          break;
        }
        buffer += decoder.decode(value, { stream: true });
        const { frames, rest } = parseSseFrames(buffer);
        buffer = rest;

        for (const frame of frames) {
          if (!frame.trim()) {
            continue;
          }
          const { event, data } = parseSseEvent(frame);
          if (event === "conversation") {
            activeConversationId.value = data.conversation_id || null;
          } else if (event === "mode") {
            assistantMessage.answer_mode = data.mode || null;
          } else if (event === "status") {
            assistantMessage.text = data.delta || "";
            scrollChatToBottom();
          } else if (event === "answer") {
            if (!answerStarted) {
              assistantMessage.text = data.delta || "";
              answerStarted = true;
            } else {
              assistantMessage.text += data.delta || "";
            }
            scrollChatToBottom();
          } else if (event === "sources") {
            assistantMessage.sources = data.sources || [];
            scrollChatToBottom();
          } else if (event === "error") {
            throw new Error(data.detail || "流式回答失败");
          }
        }
      }
      await loadChatConversations(activeConversationId.value, {
        historyShowLoading: false,
        historyScrollToBottomOnLoad: true,
      });
    } catch (error) {
      assistantMessage.text = error.message;
      assistantMessage.answer_mode = assistantMessage.answer_mode || "chunk";
      assistantMessage.sources = [];
      setStatus(chatStatus, error.message, true);
      scrollChatToBottom();
    }
  }

  async function initialize() {
    await loadSettings();
    await refreshSession();
    if (!session.loggedIn) {
      return;
    }
    await Promise.allSettled([loadFolders(), loadChatConversations()]);
  }

  function cleanup() {
    if (qrPollTimer) {
      clearInterval(qrPollTimer);
      qrPollTimer = null;
    }
    stopAllPollers();
  }

  watch(chatScopeMode, () => {
    clearStatus(chatStatus);
  });

  return {
    sessionStatus,
    syncStatus,
    chatStatus,
    qrStatus,
    settingsStatus,
    qrSvg,
    qrModalOpen,
    folders,
    selectedFolderId,
    selectedVideoBvid,
    chatInput,
    chatScopeMode,
    chatScopeFolderId,
    activeConversationId,
    chatConversations,
    chatMessages,
    chatHistoryLoading,
    chatConversationsLoading,
    deletingConversationId,
    processingSettings,
    session,
    documentViewerOpen,
    documentViewerMode,
    documentViewerVideoBvid,
    documentViewerTitle,
    documentViewerPanes,
    selectedFolder,
    selectedVideo,
    selectedChatFolder,
    selectedConversation,
    activeDocumentPane,
    chatPlaceholder,
    setChatStreamEl,
    toggleMessageSources,
    closeQrModal,
    closeDocumentViewer,
    loadSettings,
    saveSettings,
    resetAllProcessedContent,
    refreshSession,
    startQrLogin,
    loadFolders,
    loadChatHistory,
    loadChatConversations,
    createConversation,
    selectConversation,
    deleteConversation,
    syncFolder,
    openFolder,
    selectVideo,
    loadDocumentPane,
    openDocumentViewer,
    switchDocumentViewerMode,
    generateSummary,
    processSelectedVideo,
    resetSelectedVideo,
    saveSelectedVideoTags,
    askQuestion,
    initialize,
    cleanup,
  };
});

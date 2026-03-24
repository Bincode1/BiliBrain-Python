<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
import { marked } from "marked";

const STEP_ORDER = ["audio", "transcript", "index"];
const STEP_LABELS = {
  audio: "提取音频",
  transcript: "转写",
  index: "建索引",
};
const STATUS_LABELS = {
  pending: "未开始",
  running: "处理中",
  done: "已完成",
  failed: "失败",
};

function createStatus() {
  return reactive({ show: false, error: false, message: "" });
}

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
const chatStreamEl = ref(null);
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

let qrPollTimer = null;
const processPollers = new Map();

const selectedFolder = computed(() => folders.value.find((folder) => String(folder.folder_id) === String(selectedFolderId.value)) || null);
const selectedVideo = computed(() => selectedFolder.value?.videos.find((video) => video.bvid === selectedVideoBvid.value) || null);
const selectedChatFolder = computed(() => folders.value.find((folder) => String(folder.folder_id) === String(chatScopeFolderId.value)) || null);
const selectedConversation = computed(() =>
  chatConversations.value.find((item) => Number(item.conversation_id) === Number(activeConversationId.value)) || null
);
const documentViewerOpen = ref(false);
const documentViewerMode = ref("summary");
const documentViewerVideoBvid = ref("");
const documentViewerTitle = ref("");
const documentViewerPanes = reactive({
  summary: { loading: false, text: "", meta: "", error: "", loadedBvid: "" },
  transcript: { loading: false, text: "", meta: "", error: "", loadedBvid: "" },
});
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

function escapeHtml(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function renderMarkdown(text, sources = []) {
  if (!text) return "";
  const html = marked.parse(text);
  if (!Array.isArray(sources) || !sources.length) {
    return html;
  }
  const sourceMap = new Map(
    sources
      .map((source) => [Number(source.ref_index), source])
      .filter(([index]) => Number.isFinite(index) && index > 0)
  );
  return html.replace(/【(\d+)】/g, (_, rawIndex) => {
    const index = Number(rawIndex);
    const source = sourceMap.get(index);
    if (!source?.jump_url) {
      return `【${rawIndex}】`;
    }
    const label = `资料 ${index}`;
    const title = `${source.video_title || "视频片段"} ${source.timestamp ? `· ${source.timestamp}` : ""}`;
    return `<a class="inline-citation" href="${escapeHtml(source.jump_url)}" target="_blank" rel="noreferrer" title="${escapeHtml(title)}">${escapeHtml(label)}</a>`;
  });
}

function normalizeChatMessage(message) {
  return {
    message_id: message.message_id || null,
    conversation_id: message.conversation_id || activeConversationId.value || null,
    role: message.role === "assistant" ? "assistant" : "user",
    text: message.text ?? message.content ?? "",
    answer_mode: message.answer_mode || null,
    sources: Array.isArray(message.sources)
      ? message.sources.map((source, index) => ({
          ...source,
          ref_index: Number(source.ref_index || index + 1),
        }))
      : [],
    sourcesExpanded: Boolean(message.sourcesExpanded),
    created_at: message.created_at || "",
  };
}

function sourcePreviewTitle(source) {
  const title = String(source?.video_title || "").trim();
  return title.length > 20 ? `${title.slice(0, 20)}…` : title;
}

function toggleMessageSources(message) {
  message.sourcesExpanded = !message.sourcesExpanded;
}

function messageModeLabel(message) {
  if (message.answer_mode === "summary") {
    return "摘要回答";
  }
  if (message.answer_mode === "chunk") {
    return "检索回答";
  }
  return "";
}

function messageSourceKind(message) {
  const firstSource = Array.isArray(message?.sources) ? message.sources[0] : null;
  return firstSource?.source_kind === "summary" ? "summary" : "chunk";
}

function messageSourceLabel(message) {
  return messageSourceKind(message) === "summary" ? "摘要来源" : "片段来源";
}

function sourceMetaLabel(source) {
  if (source?.source_kind === "summary") {
    return `视频摘要 · ${source.up_name || "未知 UP"}`;
  }
  return `${source.timestamp || "片段"} · ${source.up_name || "未知 UP"}`;
}

function normalizeConversation(conversation) {
  return {
    conversation_id: conversation.conversation_id || null,
    folder_id: conversation.folder_id ?? null,
    title: conversation.title || "",
    message_count: Number(conversation.message_count || 0),
    created_at: conversation.created_at || "",
    updated_at: conversation.updated_at || "",
  };
}

function conversationLabel(conversation, index = 0) {
  const title = String(conversation?.title || "").trim();
  if (title) {
    return title;
  }
  return `新对话 ${index + 1}`;
}

function conversationShortLabel(conversation, index = 0) {
  const label = conversationLabel(conversation, index);
  return label.length > 18 ? `${label.slice(0, 18)}…` : label;
}


function scrollChatToBottom() {
  nextTick(() => {
    if (!chatStreamEl.value) {
      return;
    }
    chatStreamEl.value.scrollTop = chatStreamEl.value.scrollHeight;
  });
}

function statusClass(status) {
  return {
    status: true,
    show: status.show,
    error: status.error,
  };
}

function setStatus(target, message, isError = false) {
  target.message = message;
  target.error = isError;
  target.show = Boolean(message);
}

function clearStatus(target) {
  target.message = "";
  target.error = false;
  target.show = false;
}

function formatDuration(seconds) {
  const total = Number(seconds || 0);
  const minutes = Math.floor(total / 60);
  const remain = total % 60;
  return `${String(minutes).padStart(2, "0")}:${String(remain).padStart(2, "0")}`;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const contentType = response.headers.get("content-type") || "";
  if (!contentType.includes("application/json")) {
    const raw = await response.text();
    throw new Error(`接口没有返回 JSON。响应片段：${raw.slice(0, 120)}`);
  }
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.detail || "请求失败");
  }
  return data;
}

function buildStepItems(pipeline) {
  return STEP_ORDER.map((step) => {
    const item = pipeline?.[step] || {};
    return {
      step,
      label: STEP_LABELS[step],
      status: item.status || "pending",
      status_label: item.status_label || STATUS_LABELS[item.status] || item.status || "pending",
      updated_at: item.updated_at || "",
      error: item.error || "",
      substage_label: item.substage_label || "",
      count: Number(item.count || 0),
      segment_count: Number(item.segment_count || 0),
    };
  });
}

function actionLabelFromStatus(status) {
  if (status === "indexed") {
    return "已转写入库";
  }
  if (status === "failed" || status === "partial") {
    return "重试处理";
  }
  if (status === "processing") {
    return "处理中";
  }
  return "开始处理";
}

function normalizeCoverUrl(url) {
  const raw = String(url || "").trim();
  if (!raw) {
    return "";
  }
  if (raw.startsWith("//")) {
    return `https:${raw}`;
  }
  return raw;
}

function videoWatchUrl(video) {
  if (!video || video.is_invalid || !video.bvid || String(video.bvid).startsWith("invalid:")) {
    return "";
  }
  return `https://www.bilibili.com/video/${encodeURIComponent(video.bvid)}/`;
}

function openVideoLink(video) {
  const url = videoWatchUrl(video);
  if (!url) {
    return;
  }
  window.open(url, "_blank", "noopener,noreferrer");
}

function decorateVideo(video) {
  return {
    ...video,
    cover_url: normalizeCoverUrl(video.cover_url),
    watch_url: videoWatchUrl(video),
    is_invalid: Boolean(video.is_invalid),
    coverLoadFailed: false,
    manual_tags: Array.isArray(video.manual_tags) ? video.manual_tags : [],
    manualTagsInput: Array.isArray(video.manual_tags) ? video.manual_tags.join(", ") : "",
    has_summary: Boolean(video.has_summary),
    summary_updated_at: video.summary_updated_at || "",
    summaryBusy: false,
    steps: buildStepItems(video.pipeline),
    processActionLabel: actionLabelFromStatus(video.sync_status),
    processBusy: false,
  };
}

function decorateFolder(folder) {
  return {
    ...folder,
    expanded: false,
    loadingVideos: false,
    videoError: "",
    fields: [],
    videos: [],
  };
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

function firstSelectableVideo(videos) {
  return (videos || []).find((video) => !video.is_invalid) || null;
}

function hasTranscript(video) {
  return Boolean(video && (Number(video.transcript_segment_count || 0) > 0 || video.transcript_updated_at));
}

function canOpenSummary(video) {
  return Boolean(video?.has_summary);
}

function canGenerateSummary(video) {
  return Boolean(video && hasTranscript(video) && !video.has_summary && !video.summaryBusy);
}

function canOpenTranscript(video) {
  return hasTranscript(video);
}

function summaryStateTone(video) {
  if (!video) {
    return "pending";
  }
  if (video.has_summary) {
    return "done";
  }
  if (video.processBusy && video.sync_status === "indexed") {
    return "processing";
  }
  if (hasTranscript(video)) {
    return "ready";
  }
  return "pending";
}

function summaryStateLabel(video) {
  if (!video) {
    return "摘要待生成";
  }
  if (video.has_summary) {
    return video.summary_updated_at ? `摘要已生成 · ${video.summary_updated_at}` : "摘要已生成";
  }
  if (video.processBusy && video.sync_status === "indexed") {
    return "正在整理摘要";
  }
  if (hasTranscript(video)) {
    return "可手动生成摘要";
  }
  return "需要先完成转写";
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

function closeQrModal() {
  qrModalOpen.value = false;
  qrSvg.value = "";
  clearStatus(qrStatus);
  if (qrPollTimer) {
    clearInterval(qrPollTimer);
    qrPollTimer = null;
  }
}

function applyProcessStatus(video, status) {
  video.sync_status = status.overall_status;
  video.chunk_count = Number(status.chunk_count || 0);
  video.error_msg = status.error_msg || "";
  video.transcript_source = status.transcript_source || "未转写";
  video.transcript_segment_count = Number(status.transcript_segment_count || 0);
  video.transcript_updated_at = status.transcript_updated_at || "";
  video.has_summary = Boolean(status.has_summary);
  video.summary_updated_at = status.summary_updated_at || "";
  video.manual_tags = Array.isArray(status.manual_tags) ? status.manual_tags : [];
  video.manualTagsInput = video.manual_tags.join(", ");
  video.steps = Array.isArray(status.steps) ? status.steps : video.steps;
  video.processActionLabel = status.action_label || "开始处理";
  video.over_limit = Boolean(status.over_limit);
  video.max_video_minutes = Number(status.max_video_minutes || processingSettings.max_video_minutes);
}

function videoTone(video) {
  if (video.is_invalid) {
    return "invalid";
  }
  if (video.sync_status === "indexed") {
    return "done";
  }
  if (video.sync_status === "failed") {
    return "failed";
  }
  if (video.sync_status === "processing") {
    return "processing";
  }
  if (video.sync_status === "partial") {
    return "partial";
  }
  return "pending";
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
          setStatus(qrStatus, `验证完成，正在刷新页面…`);
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

async function loadChatHistory() {
  if (!session.loggedIn) {
    activeConversationId.value = null;
    chatConversations.value = [];
    chatMessages.value = [];
    return;
  }

  chatHistoryLoading.value = true;
  try {
    const params = new URLSearchParams();
    if (activeConversationId.value) {
      params.set("conversation_id", String(activeConversationId.value));
    }
    const query = params.size ? `?${params.toString()}` : "";
    const data = await api(`/api/chat/history${query}`);
    activeConversationId.value = data.conversation_id || null;
    chatMessages.value = Array.isArray(data.messages) ? data.messages.map(normalizeChatMessage) : [];
    scrollChatToBottom();
  } catch (error) {
    activeConversationId.value = null;
    chatMessages.value = [];
    setStatus(chatStatus, error.message, true);
  } finally {
    chatHistoryLoading.value = false;
  }
}

async function loadChatConversations(preferredConversationId = null) {
  if (!session.loggedIn) {
    activeConversationId.value = null;
    chatConversations.value = [];
    chatMessages.value = [];
    return;
  }

  chatConversationsLoading.value = true;
  try {
    const data = await api("/api/chat/conversations");
    chatConversations.value = Array.isArray(data.conversations) ? data.conversations.map(normalizeConversation) : [];

    const preferredId = preferredConversationId ?? activeConversationId.value ?? data.active_conversation_id ?? null;
    const exists = chatConversations.value.some((item) => Number(item.conversation_id) === Number(preferredId));
    activeConversationId.value = exists ? Number(preferredId) : (chatConversations.value[0]?.conversation_id || null);
    await loadChatHistory();
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
  const label = conversation ? conversationLabel(conversation) : "这个会话";
  if (!window.confirm(`确定删除“${label}”吗？聊天记录会一起删除。`)) {
    return;
  }

  try {
    deletingConversationId.value = Number(conversationId);
    clearStatus(chatStatus);
    const data = await api(`/api/chat/conversations/${encodeURIComponent(conversationId)}`, {
      method: "DELETE",
    });
    chatConversations.value = Array.isArray(data.conversations) ? data.conversations.map(normalizeConversation) : [];
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
  if (!video || !hasTranscript(video) || video.summaryBusy) {
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
    documentViewerPanes.summary.text = data.text || "";
    documentViewerPanes.summary.meta = `摘要已整理 · 更新时间 ${data.updated_at || "未知"}`;
    documentViewerPanes.summary.error = "";
    documentViewerPanes.summary.loadedBvid = video.bvid;
    if (openViewer) {
      documentViewerMode.value = "summary";
      primeDocumentViewer(video);
      documentViewerPanes.summary.text = data.text || "";
      documentViewerPanes.summary.meta = `摘要已整理 · 更新时间 ${data.updated_at || "未知"}`;
      documentViewerPanes.summary.error = "";
      documentViewerPanes.summary.loadedBvid = video.bvid;
      documentViewerOpen.value = true;
    }
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
      applyProcessStatus(video, data);
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
    applyProcessStatus(video, data);
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
    applyProcessStatus(video, data);
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

function parseTagInput(raw) {
  return String(raw || "")
    .split(/[,，\n]+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function parseSseFrames(buffer) {
  const normalized = buffer.replace(/\r\n/g, "\n");
  const frames = normalized.split("\n\n");
  return {
    frames: frames.slice(0, -1),
    rest: frames.at(-1) || "",
  };
}

function parseSseEvent(frame) {
  let event = "message";
  const dataLines = [];

  for (const line of frame.split("\n")) {
    if (!line || line.startsWith(":")) {
      continue;
    }
    if (line.startsWith("event:")) {
      event = line.slice(6).trim();
      continue;
    }
    if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).trimStart());
    }
  }

  const rawData = dataLines.join("\n");
  return {
    event,
    data: rawData ? JSON.parse(rawData) : {},
  };
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

  const assistantMessage = reactive(normalizeChatMessage({ role: "assistant", text: "", sources: [] }));
  chatMessages.value.push(normalizeChatMessage({ role: "user", text: query }));
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
    await loadChatConversations(activeConversationId.value);
  } catch (error) {
    assistantMessage.text = error.message;
    assistantMessage.answer_mode = assistantMessage.answer_mode || "chunk";
    assistantMessage.sources = [];
    setStatus(chatStatus, error.message, true);
    scrollChatToBottom();
  }
}

onMounted(async () => {
  await loadSettings();
  await refreshSession();
  if (!session.loggedIn) {
    return;
  }
  await Promise.allSettled([loadFolders(), loadChatConversations()]);
});

watch(chatScopeMode, () => {
  clearStatus(chatStatus);
});

onBeforeUnmount(() => {
  if (qrPollTimer) {
    clearInterval(qrPollTimer);
  }
  stopAllPollers();
});
</script>

<template>
  <div class="app-shell">
    <aside class="sidebar">
      <div class="sidebar-top">
        <div class="identity-card compact-topbar">
          <div class="topbar-main">
            <div class="brand-block">
              <div class="brand-mark">B</div>
              <div class="brand-copy">
                <span class="brand-title">BiliBrain</span>
                <span class="brand-caption">私人技术档案库</span>
              </div>
            </div>
            <div class="account-meta compact-account">
              <span class="account-label">当前账号</span>
              <span class="account-name">{{ session.loggedIn ? session.userName : "未登录" }}</span>
            </div>
          </div>
          <button class="switch-account compact-switch" type="button" @click="startQrLogin">
            {{ session.loggedIn ? "换账号" : "扫码登录" }}
          </button>
        </div>

        <div class="control-strip compact-controls">
          <div class="control-inline compact-inline">
            <span class="control-label-inline">时长</span>
            <label class="setting-mini compact-setting">
              <input v-model="processingSettings.max_video_minutes" type="number" min="1" max="300" />
            </label>
            <button class="ghost-button small" :disabled="processingSettings.saving" type="button" @click="saveSettings">保存</button>
          </div>
          <button class="ghost-button small danger-ghost subtle-reset" type="button" @click="resetAllProcessedContent">重置已加载</button>
        </div>
      </div>
        <div :class="statusClass(settingsStatus)">{{ settingsStatus.message }}</div>

        <div :class="statusClass(syncStatus)">{{ syncStatus.message }}</div>

        <section class="folders-section">
          <div class="folders-header">收藏夹</div>
          <div v-if="folders.length" class="folder-list folder-scroll">
            <article v-for="folder in folders" :key="folder.folder_id" class="folder-card">
              <button class="folder-toggle" type="button" @click="openFolder(folder)">
                <span>
                  <strong>{{ folder.title }}</strong>
                  <em>{{ folder.media_count }} 个视频 · 已入库 {{ folder.synced_videos || 0 }}</em>
                </span>
                <span class="folder-id">ID {{ folder.folder_id }}</span>
              </button>

              <div class="folder-ops">
                <button class="ghost-button" type="button" @click="syncFolder(folder)">同步元数据</button>
              </div>

              <div v-if="folder.expanded" class="video-stack">
                <div v-if="folder.loadingVideos" class="muted-box">正在读取视频列表...</div>
                <div v-else-if="folder.videoError" class="muted-box danger-text">{{ folder.videoError }}</div>
                <button
                  v-for="video in folder.videos"
                  :key="video.bvid"
                  class="video-list-item"
                  :class="[{ active: selectedVideoBvid === video.bvid && !video.is_invalid }, videoTone(video)]"
                  type="button"
                  :disabled="video.is_invalid"
                  @click="selectVideo(folder, video)"
                >
                  <div
                    class="video-row-cover"
                    :class="{ empty: !video.cover_url, clickable: !!video.watch_url }"
                    @click.stop="openVideoLink(video)"
                  >
                    <img
                      v-if="video.cover_url && !video.coverLoadFailed"
                      :src="video.cover_url"
                      :alt="video.title"
                      loading="lazy"
                      referrerpolicy="no-referrer"
                      @error="video.coverLoadFailed = true"
                    />
                    <span v-else>{{ video.is_invalid ? "失效" : "封面" }}</span>
                  </div>
                  <div class="video-row-body">
                    <div class="video-row-head">
                      <strong>{{ video.title }}</strong>
                      <div class="video-row-head-side">
                        <span class="state-dot">{{ video.is_invalid ? "已失效" : (video.sync_status || "pending") }}</span>
                        <span
                          v-if="video.watch_url"
                          class="video-link-chip"
                          @click.stop="openVideoLink(video)"
                        >
                          访问
                        </span>
                      </div>
                    </div>
                    <div class="video-row-meta">
                      <template v-if="video.is_invalid">
                        <span>该收藏内容已失效</span>
                        <span>无法处理或转写</span>
                      </template>
                      <template v-else>
                        <span>{{ formatDuration(video.duration) }}</span>
                        <span>{{ video.up_name || "未知 UP" }}</span>
                        <span>片段 {{ video.chunk_count || 0 }}</span>
                      </template>
                    </div>
                  </div>
                </button>
                <div v-if="!folder.loadingVideos && !folder.videoError && !folder.videos.length" class="muted-box">
                  当前收藏夹还没有视频。
                </div>
              </div>
            </article>
          </div>
          <div v-else class="muted-box">{{ session.loggedIn ? "还没有收藏夹数据。" : "先扫码登录，页面会自动读取收藏夹。" }}</div>
        </section>
      </aside>

      <section class="workspace">
        <section class="panel chat-panel">
          <div class="chat-layout">
            <div class="chat-main-column">
              <div class="chat-reading-head">
                <div class="chat-reading-label">当前会话</div>
                <div class="chat-reading-title" :title="selectedConversation ? conversationLabel(selectedConversation) : '未选择会话'">
                  {{ selectedConversation ? conversationLabel(selectedConversation) : "未选择会话" }}
                </div>
              </div>

              <div :class="statusClass(chatStatus)">{{ chatStatus.message }}</div>

              <div ref="chatStreamEl" class="chat-stream">
                <div v-if="chatHistoryLoading" class="empty-state chat-empty">
                  正在加载历史对话...
                </div>
                <template v-else-if="chatMessages.length">
                  <article v-for="(message, index) in chatMessages" :key="message.message_id || index" class="message" :class="message.role">
                    <div class="message-head">
                      <div class="message-role">{{ message.role === "user" ? "你" : "BiliBrain" }}</div>
                      <span
                        v-if="message.role === 'assistant' && message.answer_mode"
                        class="message-mode-badge"
                        :class="message.answer_mode"
                      >
                        {{ messageModeLabel(message) }}
                      </span>
                    </div>
                    <div class="message-body" v-html="renderMarkdown(message.text, message.sources)"></div>
                    <div v-if="message.sources?.length" class="source-panel">
                      <div class="source-summary">
                        <div class="source-summary-copy">
                          <div class="source-summary-head">
                            <div class="source-label">{{ messageSourceLabel(message) }}</div>
                            <button class="ghost-button small source-toggle-button" type="button" @click="toggleMessageSources(message)">
                              {{ message.sourcesExpanded ? "收起来源" : `展开 ${message.sources.length} 条来源` }}
                            </button>
                          </div>
                          <div v-if="!message.sourcesExpanded" class="source-chip-row">
                            <a
                              v-for="source in message.sources.slice(0, 3)"
                              :key="`compact-${source.ref_index}`"
                              :href="source.jump_url"
                              target="_blank"
                              rel="noreferrer"
                              class="source-chip"
                            >
                              <span class="source-ref-mini">资料 {{ source.ref_index }}</span>
                              <strong>{{ sourcePreviewTitle(source) }}</strong>
                              <span>{{ source.timestamp }}</span>
                            </a>
                            <span v-if="message.sources.length > 3" class="source-chip muted-more">
                              还有 {{ message.sources.length - 3 }} 条
                            </span>
                          </div>
                          <div v-else class="source-list">
                            <a
                              v-for="(source, sourceIndex) in message.sources"
                              :key="sourceIndex"
                              :href="source.jump_url"
                              target="_blank"
                              rel="noreferrer"
                              class="source-item"
                            >
                              <span class="source-ref">资料 {{ source.ref_index }}</span>
                              <div class="source-copy">
                                <strong>{{ source.video_title }}</strong>
                                <span>{{ sourceMetaLabel(source) }}</span>
                              </div>
                            </a>
                          </div>
                        </div>
                      </div>
                    </div>
                  </article>
                </template>
                <div v-else class="empty-state chat-empty">
                  {{ chatConversations.length ? "当前会话还没有消息，直接开始提问即可。" : "先新建一个会话，或者直接提问自动创建会话。" }}
                </div>
              </div>

              <div class="composer">
                <textarea v-model="chatInput" :placeholder="chatPlaceholder" />
                <div class="composer-toolbar">
                  <div class="composer-scope-group">
                    <label class="composer-scope-pill">
                      <select
                        v-model="chatScopeMode"
                        :title="chatScopeMode === 'video' ? (selectedVideo?.title || '当前视频') : (chatScopeMode === 'folder' ? (selectedChatFolder?.title || '指定收藏夹') : '全部已入库')"
                      >
                        <option value="video">当前视频</option>
                        <option value="folder">指定收藏夹</option>
                        <option value="global">全部已入库</option>
                      </select>
                    </label>
                    <label v-if="chatScopeMode === 'folder'" class="composer-scope-pill composer-folder-pill">
                      <select v-model="chatScopeFolderId" :disabled="!folders.length" title="选择收藏夹">
                        <option value="" disabled>{{ folders.length ? "选择收藏夹" : "暂无收藏夹" }}</option>
                        <option v-for="folder in folders" :key="folder.folder_id" :value="String(folder.folder_id)">
                          {{ folder.title }}
                        </option>
                      </select>
                    </label>
                  </div>
                  <button type="button" @click="askQuestion">发送</button>
                </div>
              </div>
            </div>

            <aside class="chat-side-column">
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
                    @click="processSelectedVideo"
                  >
                    {{ selectedVideo.processBusy ? "处理中..." : (selectedVideo.processActionLabel || "处理") }}
                  </button>
                  <button class="ghost-button" type="button" @click="resetSelectedVideo">重置</button>
                  <button
                    class="ghost-button"
                    type="button"
                    :disabled="!(canOpenSummary(selectedVideo) || canGenerateSummary(selectedVideo))"
                    @click="selectedVideo?.has_summary ? openDocumentViewer('summary', selectedVideo) : generateSummary(selectedVideo)"
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
                    @click="openDocumentViewer('transcript', selectedVideo)"
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

              <section class="side-card conversation-side-card">
                <div class="side-card-head">
                  <div>
                    <div class="side-card-label">对话</div>
                    <h3>会话列表</h3>
                  </div>
                  <button class="ghost-button small" type="button" @click="createConversation">新建</button>
                </div>
                <div class="conversation-side-list">
                  <div v-if="chatConversationsLoading" class="conversation-popover-empty">正在读取会话...</div>
                  <div v-else-if="!chatConversations.length" class="conversation-popover-empty">还没有会话。</div>
                  <div v-else class="conversation-popover-list">
                    <article
                      v-for="(conversation, index) in chatConversations"
                      :key="conversation.conversation_id"
                      class="conversation-popover-item"
                      :class="{ active: Number(activeConversationId) === Number(conversation.conversation_id) }"
                    >
                      <button
                        class="conversation-main"
                        :disabled="chatConversationsLoading && Number(activeConversationId) === Number(conversation.conversation_id)"
                        type="button"
                        @click="selectConversation(conversation.conversation_id)"
                        :title="conversationLabel(conversation, index)"
                      >
                        <span class="conversation-title">{{ conversationShortLabel(conversation, index) }}</span>
                      </button>
                      <button
                        class="conversation-delete"
                        type="button"
                        :disabled="Number(deletingConversationId) === Number(conversation.conversation_id)"
                        @click="deleteConversation(conversation.conversation_id)"
                        title="删除会话"
                      >
                        ×
                      </button>
                    </article>
                  </div>
                </div>
              </section>
            </aside>
          </div>
        </section>
      </section>

    <div v-if="documentViewerOpen" class="modal-shell document-modal-shell" @click.self="closeDocumentViewer">
      <div class="modal-card document-modal">
        <div class="document-modal-head">
          <div class="document-modal-copy">
            <div class="side-card-label">当前视频资料</div>
            <h2 :title="documentViewerTitle">{{ documentViewerTitle }}</h2>
          </div>
          <button class="ghost-button small" type="button" @click="closeDocumentViewer">关闭</button>
        </div>
        <div class="document-mode-switch">
          <button type="button" :class="{ active: documentViewerMode === 'summary' }" @click="switchDocumentViewerMode('summary')">摘要</button>
          <button type="button" :class="{ active: documentViewerMode === 'transcript' }" @click="switchDocumentViewerMode('transcript')">转写</button>
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

    <div v-if="qrModalOpen" class="modal-shell" @click.self="closeQrModal">
      <div class="modal-card">
        <div class="panel-head">
          <h2>扫码登录 Bilibili</h2>
          <p>扫描后会显示“等待验证”，验证完成后页面会自动刷新并重新加载收藏夹。</p>
        </div>
        <div class="qr-panel modal-qr" v-html="qrSvg || '正在生成二维码…'"></div>
        <div :class="statusClass(qrStatus)">{{ qrStatus.message }}</div>
        <div class="modal-actions">
          <button class="ghost-button" type="button" @click="closeQrModal">关闭</button>
        </div>
      </div>
    </div>
  </div>
</template>

import { computed, nextTick, reactive, ref, watch } from "vue";
import { defineStore } from "pinia";

import { clearStatus, createStatus, setStatus } from "@/composables/useStatus";
import { api } from "@/services/http";
import { normalizeChatMessage, normalizeConversation } from "@/utils/chat";
import { parseSseEvent, parseSseFrames } from "@/utils/sse";
import { useAuthStore } from "./auth";
import { useDialogStore } from "./dialog";
import { useFoldersStore } from "./folders";

const SCOPE_VIDEO = "video";
const SCOPE_FOLDER = "folder";
const SCOPE_GLOBAL = "global";
const STORAGE_KEY = "bilibrain_workspace_state";

export const useChatStore = defineStore("chat", () => {
  const chatStatus = createStatus();
  const chatInput = ref("");
  const skillAgentPendingApproval = ref(null);
  const chatScopeMode = ref(SCOPE_FOLDER);
  const chatScopeFolderId = ref("");
  const chatScopeVideoBvid = ref("");
  const activeConversationId = ref(null);
  const chatConversations = ref([]);
  const chatMessages = ref([]);
  const chatHistoryLoading = ref(false);
  const chatConversationsLoading = ref(false);
  const deletingConversationId = ref(null);
  const renamingConversationId = ref(null);
  let chatStreamEl = null;
  let smartScrollHandle = null;

  // --- localStorage persistence ---
  function loadPersistedState() {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      if (saved) {
        const state = JSON.parse(saved);
        if (state.chatScopeMode) chatScopeMode.value = state.chatScopeMode;
        if (state.chatScopeFolderId) chatScopeFolderId.value = state.chatScopeFolderId;
        if (state.chatScopeVideoBvid) chatScopeVideoBvid.value = state.chatScopeVideoBvid;
      }
    } catch {
      // ignore
    }
  }

  function savePersistedState() {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      const state = saved ? JSON.parse(saved) : {};
      state.chatScopeMode = chatScopeMode.value;
      state.chatScopeFolderId = chatScopeFolderId.value;
      state.chatScopeVideoBvid = chatScopeVideoBvid.value;
      localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
    } catch {
      // ignore
    }
  }

  watch(chatScopeMode, savePersistedState);
  watch(chatScopeFolderId, (nextFolderId) => {
    savePersistedState();
    if (!nextFolderId) { chatScopeVideoBvid.value = ""; return; }
    const foldersStore = useFoldersStore();
    const folder = foldersStore.findFolder(nextFolderId);
    if (!folder) { chatScopeVideoBvid.value = ""; return; }
    const hasCurrentVideo = (folder.videos || []).some((video) => video.bvid === chatScopeVideoBvid.value && !video.is_invalid);
    if (!hasCurrentVideo && chatScopeMode.value !== SCOPE_VIDEO) {
      chatScopeVideoBvid.value = "";
    }
  });
  watch(chatScopeVideoBvid, savePersistedState);
  loadPersistedState();

  // --- Computed ---
  const foldersStore = useFoldersStore();

  const selectedChatFolder = computed(() => {
    return foldersStore.folders.find((folder) => String(folder.folder_id) === String(chatScopeFolderId.value)) || null;
  });
  const selectedChatVideo = computed(() => selectedChatFolder.value?.videos.find((video) => video.bvid === chatScopeVideoBvid.value) || null);
  const chatScopeVideos = computed(() => (selectedChatFolder.value?.videos || []).filter((video) => !video.is_invalid));
  const selectedConversation = computed(() =>
    chatConversations.value.find((item) => Number(item.conversation_id) === Number(activeConversationId.value)) || null
  );
  const chatPlaceholder = computed(() => {
    if (chatScopeMode.value === SCOPE_VIDEO) {
      return "例如：这个视频里讲了什么内容？帮我整理成笔记。";
    }
    if (chatScopeMode.value === SCOPE_FOLDER) {
      return "例如：请帮我梳理这个收藏夹里的学习路线。";
    }
    return "例如：哪些已入库视频提到 LangGraph？或者帮我搜索并整理笔记。";
  });

  // --- Scroll helpers ---
  function setChatStreamEl(element) {
    chatStreamEl = element || null;
  }

  function registerSmartScrollHandle(handle) {
    smartScrollHandle = handle;
  }

  function scrollChatToBottom() {
    if (smartScrollHandle) {
      smartScrollHandle.scrollToBottomIfNear();
    } else {
      nextTick(() => {
        if (!chatStreamEl) return;
        chatStreamEl.scrollTop = chatStreamEl.scrollHeight;
      });
    }
  }

  function toggleMessageSources(message) {
    message.sourcesExpanded = !message.sourcesExpanded;
  }

  // --- Status helpers (called by other stores) ---
  function setChatStatus(message, isError = false) {
    setStatus(chatStatus, message, isError);
  }

  function clearChatStatus() {
    clearStatus(chatStatus);
  }

  // --- Chat scope ---
  async function ensureChatScopeSelection(folderId, options = {}) {
    const { loadVideos = false, autoSelectVideo = false } = options;
    const folder = foldersStore.findFolder(folderId);
    if (!folder) { chatScopeVideoBvid.value = ""; return null; }
    if (loadVideos) {
      try { await foldersStore.ensureFolderVideos(folder); } catch { return folder; }
    }
    const videos = (folder.videos || []).filter((video) => !video.is_invalid);
    const videoExists = videos.some((video) => video.bvid === chatScopeVideoBvid.value);
    if (!videoExists) {
      chatScopeVideoBvid.value = autoSelectVideo ? (videos[0]?.bvid || "") : "";
    }
    return folder;
  }

  async function setChatScopeRoot(mode) {
    chatScopeMode.value = mode;
    if (mode === SCOPE_GLOBAL) return;
    chatScopeVideoBvid.value = "";
    if (!chatScopeFolderId.value && foldersStore.folders.length) {
      chatScopeFolderId.value = String(foldersStore.folders[0].folder_id);
    }
    if (chatScopeFolderId.value) {
      await ensureChatScopeSelection(chatScopeFolderId.value, { loadVideos: true, autoSelectVideo: false });
    }
  }

  async function setChatScopeFolder(folderId) {
    const normalizedFolderId = String(folderId || "").trim();
    chatScopeFolderId.value = normalizedFolderId;
    chatScopeMode.value = SCOPE_FOLDER;
    if (!normalizedFolderId) { chatScopeVideoBvid.value = ""; return; }
    await ensureChatScopeSelection(normalizedFolderId, { loadVideos: true, autoSelectVideo: false });
  }

  async function setChatScopeTarget(targetBvid) {
    const normalizedBvid = String(targetBvid || "").trim();
    if (!chatScopeFolderId.value) { chatScopeVideoBvid.value = ""; chatScopeMode.value = SCOPE_FOLDER; return; }
    await ensureChatScopeSelection(chatScopeFolderId.value, { loadVideos: true, autoSelectVideo: false });
    if (!normalizedBvid) { chatScopeVideoBvid.value = ""; chatScopeMode.value = SCOPE_FOLDER; return; }
    chatScopeVideoBvid.value = normalizedBvid;
    chatScopeMode.value = SCOPE_VIDEO;
  }

  // --- Chat state management ---
  function resetChatStateOnLogout() {
    activeConversationId.value = null;
    chatConversations.value = [];
    chatMessages.value = [];
    skillAgentPendingApproval.value = null;
  }

  function syncActiveConversationId(conversations, preferredConversationId = null, fallbackActiveConversationId = null) {
    const preferredId = preferredConversationId ?? fallbackActiveConversationId ?? null;
    const exists = conversations.some((item) => Number(item.conversation_id) === Number(preferredId));
    activeConversationId.value = exists ? Number(preferredId) : (conversations[0]?.conversation_id || null);
  }

  function pushAgentActivity(message, field, item) {
    if (!Array.isArray(message[field])) message[field] = [];
    message[field].push({ ...item, _id: `${Date.now()}-${Math.random().toString(16).slice(2, 8)}` });
  }

  // --- Conversations ---
  async function loadChatHistory(options = {}) {
    const { showLoading = true, scrollToBottomOnLoad = true } = options;
    const authStore = useAuthStore();
    if (!authStore.session.loggedIn) { resetChatStateOnLogout(); return; }
    if (showLoading) chatHistoryLoading.value = true;
    try {
      const params = new URLSearchParams();
      if (activeConversationId.value) params.set("conversation_id", String(activeConversationId.value));
      const query = params.size ? `?${params.toString()}` : "";
      const data = await api(`/api/chat/history${query}`);
      activeConversationId.value = data.conversation_id || null;
      chatMessages.value = Array.isArray(data.messages)
        ? data.messages.map((message) => normalizeChatMessage(message, activeConversationId.value))
        : [];
    } catch (error) {
      chatMessages.value = [];
      setStatus(chatStatus, error.message, true);
    } finally {
      if (showLoading) chatHistoryLoading.value = false;
      if (scrollToBottomOnLoad) { await nextTick(); scrollChatToBottom(); }
    }
  }

  async function loadChatConversations(preferredConversationId = null, options = {}) {
    const { historyShowLoading = true, historyScrollToBottomOnLoad = true } = options;
    const authStore = useAuthStore();
    chatConversationsLoading.value = true;
    try {
      const data = await api("/api/chat/conversations");
      chatConversations.value = Array.isArray(data.conversations) ? data.conversations.map(normalizeConversation) : [];
      syncActiveConversationId(chatConversations.value, preferredConversationId, activeConversationId.value ?? data.active_conversation_id ?? null);
      await loadChatHistory({ showLoading: historyShowLoading, scrollToBottomOnLoad: historyScrollToBottomOnLoad });
    } catch {
      resetChatStateOnLogout();
    } finally {
      chatConversationsLoading.value = false;
    }
  }

  async function refreshConversationListOnly(preferredConversationId = null) {
    const authStore = useAuthStore();
    if (!authStore.session.loggedIn) return;
    try {
      const data = await api("/api/chat/conversations");
      chatConversations.value = Array.isArray(data.conversations) ? data.conversations.map(normalizeConversation) : [];
      syncActiveConversationId(chatConversations.value, preferredConversationId, activeConversationId.value);
    } catch {
      // ignore
    }
  }

  async function createConversation() {
    try {
      const data = await api("/api/chat/conversations", { method: "POST", body: JSON.stringify({}) });
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
    if (Number(activeConversationId.value) === Number(conversationId)) return;
    activeConversationId.value = Number(conversationId);
    await loadChatHistory();
  }

  async function deleteConversation(conversationId) {
    if (!conversationId) return;
    const dialogStore = useDialogStore();
    const conversation = chatConversations.value.find((item) => Number(item.conversation_id) === Number(conversationId));
    const label = conversation?.title || "这个会话";
    const confirmed = await dialogStore.confirmDialog({
      title: "删除会话",
      message: `确定删除"${label}"吗？聊天记录会一起删除。`,
      confirmLabel: "删除",
      cancelLabel: "取消",
      tone: "danger",
    });
    if (!confirmed) return;
    try {
      deletingConversationId.value = Number(conversationId);
      clearStatus(chatStatus);
      const data = await api(`/api/chat/conversations/${encodeURIComponent(conversationId)}`, { method: "DELETE" });
      await refreshConversationListOnly();
      activeConversationId.value = data.active_conversation_id || null;
      if (activeConversationId.value) { await loadChatHistory(); } else { chatMessages.value = []; }
    } catch (error) {
      setStatus(chatStatus, error.message, true);
    } finally {
      deletingConversationId.value = null;
    }
  }

  async function renameConversation(conversationId) {
    const dialogStore = useDialogStore();
    const conversation = chatConversations.value.find((item) => Number(item.conversation_id) === Number(conversationId));
    const currentTitle = String(conversation?.title || "").trim();
    const nextTitle = await dialogStore.promptDialog({
      title: "重命名会话",
      message: "给这条会话换一个更清晰的名字。",
      initialValue: currentTitle || "",
      placeholder: "请输入新的会话名称",
      confirmLabel: "保存",
    });
    if (nextTitle == null) return;
    const normalizedTitle = nextTitle.trim();
    if (!normalizedTitle) { setStatus(chatStatus, "会话名称不能为空。", true); return; }
    try {
      renamingConversationId.value = Number(conversationId);
      const data = await api(`/api/chat/conversations/${encodeURIComponent(conversationId)}`, {
        method: "PATCH",
        body: JSON.stringify({ title: normalizedTitle }),
      });
      chatConversations.value = Array.isArray(data.conversations)
        ? data.conversations.map(normalizeConversation)
        : chatConversations.value.map((item) =>
            Number(item.conversation_id) === Number(conversationId) ? { ...item, title: normalizedTitle } : item
          );
    } catch (error) {
      setStatus(chatStatus, error.message, true);
    } finally {
      renamingConversationId.value = null;
    }
  }

  // --- Unified SSE stream consumer ---
  async function consumeUnifiedStream(response, assistantMessage) {
    const dataType = response.headers.get("content-type") || "";
    if (!response.ok || !dataType.includes("text/event-stream")) {
      const raw = await response.text();
      throw new Error(raw || "请求失败");
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let answerStarted = false;

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const { frames, rest } = parseSseFrames(buffer);
      buffer = rest;
      for (const frame of frames) {
        if (!frame.trim()) continue;
        const { event, data } = parseSseEvent(frame);
        if (event === "conversation") {
          activeConversationId.value = data.conversation_id || null;
        } else if (event === "route") {
          assistantMessage.route_mode = data.route_mode || null;
        } else if (event === "mode") {
          assistantMessage.answer_mode = data.mode || null;
        } else if (event === "status") {
          assistantMessage.agent_status = data.delta || "";
          scrollChatToBottom();
        } else if (event === "answer") {
          skillAgentPendingApproval.value = null;
          if (!answerStarted) { assistantMessage.text = data.delta || ""; answerStarted = true; }
          else { assistantMessage.text += data.delta || ""; }
          scrollChatToBottom();
        } else if (event === "answer_normalized") {
          assistantMessage.text = data.text || "";
        } else if (event === "sources") {
          assistantMessage.sources = data.sources || [];
        } else if (event === "skill") {
          pushAgentActivity(assistantMessage, "skill_events", data);
        } else if (event === "tool") {
          pushAgentActivity(assistantMessage, "tool_events", data);
        } else if (event === "skills") {
          assistantMessage.active_skills = Array.isArray(data.active_skills) ? data.active_skills : [];
        } else if (event === "approval") {
          skillAgentPendingApproval.value = {
            conversationId: activeConversationId.value || null,
            sessionId: data.session_id || `conversation-${activeConversationId.value || ""}`,
            workspaceId: data.workspace_id || "",
            approvalRequest: data.approval_request || null,
          };
          assistantMessage.agent_status = "等待你审批后继续执行。";
          if (!assistantMessage.text) assistantMessage.text = "等待你审批后继续执行。";
        } else if (event === "reasoning") {
          if (!assistantMessage.reasoning_text) assistantMessage.reasoning_text = "";
          assistantMessage.reasoning_text += data.delta || "";
        } else if (event === "error") {
          throw new Error(data.detail || "流式执行失败");
        }
      }
    }
    assistantMessage._streaming = false;
  }

  // --- Ask question (unified agent) ---
  async function askQuestion(text) {
    const query = (text ?? chatInput.value).trim();
    if (!query) { setStatus(chatStatus, "请先输入问题。", true); return; }

    // Resolve scope
    let scopeFolderId = null;
    let scopeBvid = null;
    if (chatScopeMode.value === SCOPE_VIDEO) {
      if (!selectedChatFolder.value) { setStatus(chatStatus, "请先选择一个收藏夹，再指定视频。", true); return; }
      if (!selectedChatVideo.value) { setStatus(chatStatus, "请先选择一个视频，或切换到整个收藏夹 / 全部已入库。", true); return; }
      scopeFolderId = Number(selectedChatFolder.value.folder_id);
      scopeBvid = selectedChatVideo.value.bvid;
    } else if (chatScopeMode.value === SCOPE_FOLDER) {
      if (!selectedChatFolder.value) { setStatus(chatStatus, "请先选择一个收藏夹，或切换到其他范围。", true); return; }
      scopeFolderId = Number(selectedChatFolder.value.folder_id);
    }

    const assistantMessage = reactive(
      normalizeChatMessage(
        {
          role: "assistant",
          text: "正在思考...",
          sources: [],
          tool_events: [],
          skill_events: [],
          active_skills: [],
        },
        activeConversationId.value
      )
    );
    assistantMessage._streaming = true;
    chatMessages.value.push(normalizeChatMessage({ role: "user", text: query }, activeConversationId.value));
    chatMessages.value.push(assistantMessage);
    if (text == null) chatInput.value = "";
    skillAgentPendingApproval.value = null;
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
      await consumeUnifiedStream(response, assistantMessage);
      await refreshConversationListOnly(activeConversationId.value);
    } catch (error) {
      assistantMessage.text = error.message;
      assistantMessage.answer_mode = assistantMessage.answer_mode || "direct";
      assistantMessage.sources = [];
      assistantMessage._streaming = false;
      await refreshConversationListOnly(activeConversationId.value);
    }
  }

  async function resumeSkillAgentApproval(decision) {
    if (!skillAgentPendingApproval.value?.sessionId) {
      setStatus(chatStatus, "当前没有待审批的操作。", true);
      return;
    }

    // Resolve current scope for resume
    let scopeFolderId = null;
    let scopeBvid = null;
    if (chatScopeMode.value === SCOPE_VIDEO && selectedChatFolder.value && selectedChatVideo.value) {
      scopeFolderId = Number(selectedChatFolder.value.folder_id);
      scopeBvid = selectedChatVideo.value.bvid;
    } else if (chatScopeMode.value === SCOPE_FOLDER && selectedChatFolder.value) {
      scopeFolderId = Number(selectedChatFolder.value.folder_id);
    }

    const assistantMessage = reactive(
      normalizeChatMessage({ role: "assistant", text: "", sources: [], tool_events: [], skill_events: [], active_skills: [] }, activeConversationId.value)
    );
    assistantMessage._streaming = true;
    chatMessages.value.push(assistantMessage);
    try {
      const response = await fetch("/api/skill-agent/resume/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          conversation_id: skillAgentPendingApproval.value.conversationId,
          session_id: skillAgentPendingApproval.value.sessionId,
          decision,
          folder_id: scopeFolderId,
          bvid: scopeBvid,
          scope_mode: chatScopeMode.value,
        }),
      });
      skillAgentPendingApproval.value = null;
      await consumeUnifiedStream(response, assistantMessage);
    } catch (error) {
      assistantMessage.text = error.message;
      assistantMessage._streaming = false;
      await refreshConversationListOnly(activeConversationId.value);
    }
  }

  return {
    chatStatus,
    chatInput,
    skillAgentPendingApproval,
    chatScopeMode,
    chatScopeFolderId,
    chatScopeVideoBvid,
    activeConversationId,
    chatConversations,
    chatMessages,
    chatHistoryLoading,
    chatConversationsLoading,
    deletingConversationId,
    renamingConversationId,
    selectedChatFolder,
    selectedChatVideo,
    chatScopeVideos,
    selectedConversation,
    chatPlaceholder,
    setChatStreamEl,
    registerSmartScrollHandle,
    scrollChatToBottom,
    toggleMessageSources,
    setChatStatus,
    clearChatStatus,
    ensureChatScopeSelection,
    setChatScopeRoot,
    setChatScopeFolder,
    setChatScopeTarget,
    resetChatStateOnLogout,
    loadChatHistory,
    loadChatConversations,
    refreshConversationListOnly,
    createConversation,
    selectConversation,
    deleteConversation,
    renameConversation,
    askQuestion,
    resumeSkillAgentApproval,
  };
});

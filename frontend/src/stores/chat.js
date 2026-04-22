import { computed, nextTick, reactive, ref, watch } from "vue";
import { defineStore } from "pinia";

import { clearStatus, createStatus, setStatus } from "@/composables/useStatus";
import { api } from "@/services/http";
import {
  normalizeApproval,
  normalizeChatMessage,
  normalizeConversation,
  normalizeTask,
  normalizeTaskEvent,
  normalizeToolUse,
} from "@/utils/chat";
import { parseSseEvent, parseSseFrames } from "@/utils/sse";
import { useAuthStore } from "./auth";
import { useDialogStore } from "./dialog";
import { useFoldersStore } from "./folders";

const SCOPE_VIDEO = "video";
const SCOPE_FOLDER = "folder";
const SCOPE_GLOBAL = "global";
const STORAGE_KEY = "bilibrain_workspace_state";
const TRANSIENT_ASSISTANT_TEXTS = new Set(["", "正在思考...", "等待你审批后继续执行。"]);

export const useChatStore = defineStore("chat", () => {
  const chatStatus = createStatus();
  const chatInput = ref("");
  const agentPendingApproval = ref(null);
  const chatScopeMode = ref(SCOPE_FOLDER);
  const chatScopeFolderId = ref("");
  const chatScopeVideoBvid = ref("");
  const activeConversationId = ref(null);
  const chatContextUsage = ref({ conversationId: null, currentTokens: 0, limitTokens: 50000 });
  const chatConversations = ref([]);
  const chatMessages = ref([]);
  const chatTasks = ref([]);
  const chatToolUses = ref([]);
  const chatApprovals = ref([]);
  const chatTaskEvents = ref([]);
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
    chatTasks.value = [];
    chatToolUses.value = [];
    chatApprovals.value = [];
    chatTaskEvents.value = [];
    agentPendingApproval.value = null;
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

  function upsertByKey(listRef, keyField, item, normalizer = (value) => value) {
    const normalized = normalizer(item);
    const key = normalized?.[keyField];
    if (!key) return normalized;
    const next = [...listRef.value];
    const index = next.findIndex((entry) => String(entry?.[keyField] || "") === String(key));
    if (index >= 0) next[index] = { ...next[index], ...normalized };
    else next.push(normalized);
    listRef.value = next;
    return normalized;
  }

  function appendTaskEventRecord(item) {
    const normalized = normalizeTaskEvent(item);
    if (!normalized.event_id) {
      normalized.event_id = `${Date.now()}-${Math.random().toString(16).slice(2, 8)}`;
    }
    chatTaskEvents.value = [...chatTaskEvents.value, normalized];
    return normalized;
  }

  function getTaskById(taskId = null) {
    const normalizedTaskId = String(taskId || "").trim();
    if (!normalizedTaskId) return null;
    return chatTasks.value.find((item) => String(item.task_id || "").trim() === normalizedTaskId) || null;
  }

  function getToolUseById(toolUseId = null) {
    const normalizedToolUseId = String(toolUseId || "").trim();
    if (!normalizedToolUseId) return null;
    return chatToolUses.value.find((item) => String(item.tool_use_id || "").trim() === normalizedToolUseId) || null;
  }

  function getApprovalById(approvalId = null) {
    const normalizedApprovalId = String(approvalId || "").trim();
    if (!normalizedApprovalId) return null;
    return chatApprovals.value.find((item) => String(item.approval_id || "").trim() === normalizedApprovalId) || null;
  }

  function getToolUsesByTaskId(taskId = null) {
    const normalizedTaskId = String(taskId || "").trim();
    if (!normalizedTaskId) return [];
    return chatToolUses.value.filter((item) => String(item.task_id || "").trim() === normalizedTaskId);
  }

  function getApprovalsByTaskId(taskId = null) {
    const normalizedTaskId = String(taskId || "").trim();
    if (!normalizedTaskId) return [];
    return chatApprovals.value.filter((item) => String(item.task_id || "").trim() === normalizedTaskId);
  }

  function getLatestApprovalByToolUseId(taskId = null, toolUseId = null) {
    const normalizedTaskId = String(taskId || "").trim();
    const normalizedToolUseId = String(toolUseId || "").trim();
    if (!normalizedTaskId || !normalizedToolUseId) return null;
    return getApprovalsByTaskId(normalizedTaskId)
      .filter((item) => String(item.tool_use_id || "").trim() === normalizedToolUseId)
      .sort((a, b) => String(b.updated_at || b.created_at || "").localeCompare(String(a.updated_at || a.created_at || "")))[0] || null;
  }

  function getTaskEventsByTaskId(taskId = null) {
    const normalizedTaskId = String(taskId || "").trim();
    if (!normalizedTaskId) return [];
    return chatTaskEvents.value.filter((item) => String(item.task_id || "").trim() === normalizedTaskId);
  }

  function upsertTaskRecord(item) {
    const taskId = String(item?.task_id || "").trim();
    if (!taskId) return null;
    const existing = getTaskById(taskId);
    return upsertByKey(
      chatTasks,
      "task_id",
      {
        ...(existing || {}),
        ...item,
        task_id: taskId,
        conversation_id: item?.conversation_id ?? existing?.conversation_id ?? activeConversationId.value ?? null,
      },
      (value) => normalizeTask(value, activeConversationId.value)
    );
  }

  function upsertToolUseRecord(item) {
    const toolUseId = String(item?.tool_use_id || "").trim();
    if (!toolUseId) return null;
    const existing = getToolUseById(toolUseId);
    return upsertByKey(
      chatToolUses,
      "tool_use_id",
      {
        ...(existing || {}),
        ...item,
        tool_use_id: toolUseId,
      },
      normalizeToolUse
    );
  }

  function upsertApprovalRecord(item) {
    const approvalId = String(item?.approval_id || "").trim();
    if (!approvalId) return null;
    const existing = getApprovalById(approvalId);
    return upsertByKey(
      chatApprovals,
      "approval_id",
      {
        ...(existing || {}),
        ...item,
        approval_id: approvalId,
      },
      normalizeApproval
    );
  }

  function updatePendingApprovalDecision(pendingApproval, decision) {
    if (!pendingApproval?.taskId) return;
    const resolvedAt = new Date().toISOString();
    const isRejected = decision?.type === "reject";
    const approvalId = pendingApproval.approvalId || getLatestApprovalByToolUseId(
      pendingApproval.taskId,
      pendingApproval.toolUseId,
    )?.approval_id;

    if (approvalId) {
      upsertApprovalRecord({
        approval_id: approvalId,
        task_id: pendingApproval.taskId,
        tool_use_id: pendingApproval.toolUseId || null,
        status: isRejected ? "rejected" : "approved",
        decision_payload: decision || null,
        resolved_at: resolvedAt,
        updated_at: resolvedAt,
      });
    }

    if (pendingApproval.toolUseId) {
      upsertToolUseRecord({
        tool_use_id: pendingApproval.toolUseId,
        task_id: pendingApproval.taskId,
      });
    }

    upsertTaskRecord({
      task_id: pendingApproval.taskId,
      assistant_message_id: pendingApproval.assistantMessageId || null,
      status: isRejected ? "failed" : "running",
      phase: isRejected ? "rejected" : "running",
      pending_tool_use_id: "",
      failure_reason: isRejected ? String(decision?.message || "用户拒绝了当前操作。") : "",
    });
  }

  function getTaskBundle(taskId = null) {
    return {
      task: getTaskById(taskId),
      toolUses: getToolUsesByTaskId(taskId),
      approvals: getApprovalsByTaskId(taskId),
      taskEvents: getTaskEventsByTaskId(taskId),
    };
  }

  function hasTaskActivity(taskId = null) {
    const bundle = getTaskBundle(taskId);
    return !!(bundle.task || bundle.toolUses.length || bundle.approvals.length || bundle.taskEvents.length);
  }

  function normalizePendingApproval(payload, conversationId = null) {
    if (!payload || !payload.approval_request) return null;
    const resolvedConversationId = Number(payload.conversation_id || conversationId || activeConversationId.value || 0) || null;
    return {
      conversationId: resolvedConversationId,
      sessionId: payload.session_id || (resolvedConversationId ? `conversation-${resolvedConversationId}` : ""),
      workspaceId: payload.workspace_id || "",
      taskId: payload.task_id || null,
      toolUseId: payload.tool_use_id || null,
      assistantMessageId: payload.assistant_message_id || null,
      approvalId: payload.approval_id || null,
      approvalRequest: payload.approval_request || null,
      updatedAt: payload.updated_at || "",
    };
  }

  function findAssistantMessageForTask(taskId = null, assistantMessageId = null) {
    const normalizedTaskId = String(taskId || "").trim();
    const normalizedAssistantMessageId = Number(assistantMessageId || 0) || null;
    for (let index = chatMessages.value.length - 1; index >= 0; index -= 1) {
      const message = chatMessages.value[index];
      if (!message || message.role !== "assistant") continue;
      if (normalizedAssistantMessageId && Number(message.message_id) === normalizedAssistantMessageId) {
        return message;
      }
      if (normalizedTaskId && String(message.task_id || "").trim() === normalizedTaskId) {
        return message;
      }
    }
    return null;
  }

  function normalizeContextUsage(payload, conversationId = null) {
    const resolvedConversationId = Number(payload?.conversation_id || payload?.conversationId || conversationId || activeConversationId.value || 0) || null;
    return {
      conversationId: resolvedConversationId,
      currentTokens: Math.max(Number(payload?.current_tokens || payload?.currentTokens || 0), 0),
      limitTokens: Math.max(Number(payload?.limit_tokens || payload?.limitTokens || chatContextUsage.value.limitTokens || 50000), 0),
    };
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
      chatTasks.value = Array.isArray(data.tasks)
        ? data.tasks.map((item) => normalizeTask(item, activeConversationId.value))
        : [];
      chatToolUses.value = Array.isArray(data.tool_uses)
        ? data.tool_uses.map((item) => normalizeToolUse(item))
        : [];
      chatApprovals.value = Array.isArray(data.approvals)
        ? data.approvals.map((item) => normalizeApproval(item))
        : [];
      chatTaskEvents.value = Array.isArray(data.task_events)
        ? data.task_events.map((item) => normalizeTaskEvent(item))
        : [];
      agentPendingApproval.value = normalizePendingApproval(data.pending_approval, activeConversationId.value);
      chatContextUsage.value = normalizeContextUsage(data.context_usage, activeConversationId.value);
    } catch (error) {
      chatMessages.value = [];
      chatTasks.value = [];
      chatToolUses.value = [];
      chatApprovals.value = [];
      chatTaskEvents.value = [];
      agentPendingApproval.value = null;
      chatContextUsage.value = normalizeContextUsage(null, activeConversationId.value);
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
      chatTasks.value = [];
      chatToolUses.value = [];
      chatApprovals.value = [];
      chatTaskEvents.value = [];
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
    let answerStarted = !TRANSIENT_ASSISTANT_TEXTS.has(String(assistantMessage.text || ""));

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
          chatContextUsage.value = normalizeContextUsage(chatContextUsage.value, activeConversationId.value);
        } else if (event === "task") {
          if (data.task_id) assistantMessage.task_id = data.task_id;
          if (data.assistant_message_id) assistantMessage.message_id = data.assistant_message_id;
          upsertTaskRecord({
            task_id: data.task_id || assistantMessage.task_id || null,
            conversation_id: activeConversationId.value || null,
            assistant_message_id: data.assistant_message_id || assistantMessage.message_id || null,
          });
        } else if (event === "task_status") {
          if (data.task_id) assistantMessage.task_id = data.task_id;
          if (data.assistant_message_id) assistantMessage.message_id = data.assistant_message_id;
          const resolvedTaskId = data.task_id || assistantMessage.task_id || null;
          const existingTask = getTaskById(resolvedTaskId);
          const hasPendingToolUseId = Object.prototype.hasOwnProperty.call(data || {}, "pending_tool_use_id");
          upsertTaskRecord({
            task_id: resolvedTaskId,
            conversation_id: activeConversationId.value || null,
            assistant_message_id: data.assistant_message_id || assistantMessage.message_id || null,
            status: data.status || null,
            phase: data.phase || null,
            failure_reason: data.failure_reason ?? existingTask?.failure_reason ?? "",
            route_mode: data.route_mode ?? existingTask?.route_mode ?? null,
            answer_mode: data.answer_mode ?? existingTask?.answer_mode ?? null,
            pending_tool_use_id: hasPendingToolUseId
              ? (data.pending_tool_use_id || null)
              : (existingTask?.pending_tool_use_id || null),
          });
          if (data.task_id) {
            appendTaskEventRecord({
              task_id: data.task_id,
              event_type: data.status === "failed" ? "task_failed" : data.status === "completed" ? "task_completed" : "phase_changed",
              payload: data,
            });
          }
        } else if (event === "route") {
          assistantMessage.route_mode = data.route_mode || null;
          if (assistantMessage.task_id) {
            upsertTaskRecord({
              task_id: assistantMessage.task_id,
              conversation_id: activeConversationId.value || null,
              route_mode: data.route_mode || null,
            });
          }
        } else if (event === "mode") {
          assistantMessage.answer_mode = data.mode || null;
          if (assistantMessage.task_id) {
            upsertTaskRecord({
              task_id: assistantMessage.task_id,
              conversation_id: activeConversationId.value || null,
              answer_mode: data.mode || null,
            });
          }
        } else if (event === "status") {
          assistantMessage.agent_status = data.delta || "";
          scrollChatToBottom();
        } else if (event === "answer") {
          agentPendingApproval.value = null;
          if (!answerStarted) { assistantMessage.text = data.delta || ""; answerStarted = true; }
          else { assistantMessage.text += data.delta || ""; }
          scrollChatToBottom();
        } else if (event === "answer_normalized") {
          assistantMessage.text = data.text || "";
        } else if (event === "sources") {
          assistantMessage.sources = data.sources || [];
        } else if (event === "skill") {
          pushAgentActivity(assistantMessage, "skill_events", data);
          if (assistantMessage.task_id) {
            appendTaskEventRecord({
              task_id: assistantMessage.task_id,
              tool_use_id: data.id || null,
              event_type: "skill",
              payload: data,
            });
          }
        } else if (event === "tool") {
          pushAgentActivity(assistantMessage, "tool_events", data);
          if (assistantMessage.task_id) {
            appendTaskEventRecord({
              task_id: assistantMessage.task_id,
              tool_use_id: data.id || null,
              event_type: "tool",
              payload: data,
            });
          }
        } else if (event === "tool_use") {
          const normalizedToolUse = upsertToolUseRecord({
            task_id: assistantMessage.task_id || data.task_id || null,
            ...data,
          });
          if (normalizedToolUse?.task_id && assistantMessage.task_id == null) {
            assistantMessage.task_id = normalizedToolUse.task_id;
          }
        } else if (event === "skills") {
          assistantMessage.active_skills = Array.isArray(data.active_skills) ? data.active_skills : [];
          assistantMessage.loaded_skills = Array.isArray(data.loaded_skills) ? data.loaded_skills : [];
        } else if (event === "context") {
          chatContextUsage.value = normalizeContextUsage(data, activeConversationId.value);
        } else if (event === "approval") {
          const approvalId = data.approval_id || `${Date.now()}-${Math.random().toString(16).slice(2, 8)}`;
          agentPendingApproval.value = {
            conversationId: activeConversationId.value || null,
            sessionId: data.session_id || `conversation-${activeConversationId.value || ""}`,
            workspaceId: data.workspace_id || "",
            taskId: data.task_id || assistantMessage.task_id || null,
            toolUseId: data.tool_use_id || null,
            assistantMessageId: data.assistant_message_id || assistantMessage.message_id || null,
            approvalId,
            approvalRequest: data.approval_request || null,
          };
          if (data.task_id) assistantMessage.task_id = data.task_id;
          if (data.assistant_message_id) assistantMessage.message_id = data.assistant_message_id;
          if (data.task_id) {
            upsertApprovalRecord({
              approval_id: approvalId,
              task_id: data.task_id,
              tool_use_id: data.tool_use_id || null,
              status: "pending",
              request_payload: {
                session_id: data.session_id || "",
                workspace_id: data.workspace_id || "",
                approval_request: data.approval_request || null,
              },
            });
            upsertTaskRecord({
              task_id: data.task_id,
              conversation_id: activeConversationId.value || null,
              assistant_message_id: data.assistant_message_id || assistantMessage.message_id || null,
              status: "requires_action",
              phase: "waiting_approval",
              pending_tool_use_id: data.tool_use_id || null,
            });
            appendTaskEventRecord({
              task_id: data.task_id,
              tool_use_id: data.tool_use_id || null,
              event_type: "approval_requested",
              payload: data,
            });
          }
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
          loaded_skills: [],
        },
        activeConversationId.value
      )
    );
    assistantMessage._streaming = true;
    chatMessages.value.push(normalizeChatMessage({ role: "user", text: query }, activeConversationId.value));
    chatMessages.value.push(assistantMessage);
    if (text == null) chatInput.value = "";
    agentPendingApproval.value = null;
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

  async function resumeAgentApproval(decision) {
    if (!agentPendingApproval.value?.sessionId) {
      setStatus(chatStatus, "当前没有待审批的操作。", true);
      return;
    }
    const pendingApproval = agentPendingApproval.value;

    // Resolve current scope for resume
    let scopeFolderId = null;
    let scopeBvid = null;
    if (chatScopeMode.value === SCOPE_VIDEO && selectedChatFolder.value && selectedChatVideo.value) {
      scopeFolderId = Number(selectedChatFolder.value.folder_id);
      scopeBvid = selectedChatVideo.value.bvid;
    } else if (chatScopeMode.value === SCOPE_FOLDER && selectedChatFolder.value) {
      scopeFolderId = Number(selectedChatFolder.value.folder_id);
    }

    const existingAssistant = findAssistantMessageForTask(
      pendingApproval?.taskId,
      pendingApproval?.assistantMessageId,
    );
    const assistantMessage = existingAssistant || reactive(
      normalizeChatMessage({ role: "assistant", text: "", sources: [], tool_events: [], skill_events: [], active_skills: [], loaded_skills: [] }, activeConversationId.value)
    );
    assistantMessage._streaming = true;
    if (pendingApproval?.taskId) assistantMessage.task_id = pendingApproval.taskId;
    if (pendingApproval?.assistantMessageId) assistantMessage.message_id = pendingApproval.assistantMessageId;
    if (!existingAssistant) {
      chatMessages.value.push(assistantMessage);
    }
    try {
      const resolvedApprovalId = pendingApproval.approvalId || getLatestApprovalByToolUseId(
        pendingApproval.taskId,
        pendingApproval.toolUseId,
      )?.approval_id;
      const resolvedDecision = resolvedApprovalId
        ? { ...(decision || {}), approval_id: resolvedApprovalId }
        : { ...(decision || {}) };
      updatePendingApprovalDecision(pendingApproval, resolvedDecision);
      const response = await fetch("/api/agent/resume/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          conversation_id: pendingApproval.conversationId,
          task_id: pendingApproval.taskId,
          session_id: pendingApproval.sessionId,
          decision: resolvedDecision,
          folder_id: scopeFolderId,
          bvid: scopeBvid,
          scope_mode: chatScopeMode.value,
        }),
      });
      agentPendingApproval.value = null;
      await consumeUnifiedStream(response, assistantMessage);
    } catch (error) {
      assistantMessage.text = error.message;
      assistantMessage._streaming = false;
      await loadChatHistory({ showLoading: false, scrollToBottomOnLoad: false });
      await refreshConversationListOnly(activeConversationId.value);
    }
  }

  return {
    chatStatus,
    chatInput,
    agentPendingApproval,
    chatScopeMode,
    chatScopeFolderId,
    chatScopeVideoBvid,
    activeConversationId,
    chatContextUsage,
    chatConversations,
    chatMessages,
    chatTasks,
    chatToolUses,
    chatApprovals,
    chatTaskEvents,
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
    getTaskById,
    getToolUsesByTaskId,
    getApprovalsByTaskId,
    getTaskEventsByTaskId,
    getTaskBundle,
    hasTaskActivity,
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
    resumeAgentApproval,
  };
});

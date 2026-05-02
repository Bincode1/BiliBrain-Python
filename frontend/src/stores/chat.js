import { computed, nextTick, reactive, ref } from "vue";
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
import { createChatRecords } from "./chatRecords";
import { createChatEventReducer } from "./chatEventReducer";
import { createChatScope, SCOPE_FOLDER, SCOPE_VIDEO } from "./chatScope";
import { consumeSseResponse } from "./chatStream";
import { useAuthStore } from "./auth";
import { useDialogStore } from "./dialog";
import { useFoldersStore } from "./folders";

const TRANSIENT_ASSISTANT_TEXTS = new Set(["", "正在思考...", "等待你审批后继续执行。"]);

export const useChatStore = defineStore("chat", () => {
  const chatStatus = createStatus();
  const chatInput = ref("");
  const agentPendingApproval = ref(null);
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

  // --- Computed ---
  const foldersStore = useFoldersStore();
  const {
    chatScopeMode,
    chatScopeFolderId,
    chatScopeVideoBvid,
    selectedChatFolder,
    selectedChatVideo,
    chatScopeVideos,
    chatPlaceholder,
    ensureChatScopeSelection,
    setChatScopeRoot,
    setChatScopeFolder,
    setChatScopeTarget,
  } = createChatScope(foldersStore);

  const selectedConversation = computed(() =>
    chatConversations.value.find((item) => Number(item.conversation_id) === Number(activeConversationId.value)) || null
  );

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

  const chatRecords = createChatRecords({
    activeConversationId,
    chatTasks,
    chatToolUses,
    chatApprovals,
    chatTaskEvents,
  });
  const {
    appendTaskEventRecord,
    getTaskById,
    getToolUsesByTaskId,
    getApprovalsByTaskId,
    getLatestApprovalByToolUseId,
    getTaskEventsByTaskId,
    upsertTaskRecord,
    upsertToolUseRecord,
    upsertApprovalRecord,
    updatePendingApprovalDecision,
    getTaskBundle,
    hasVisibleTaskActivity,
  } = chatRecords;

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
    const reducer = createChatEventReducer({
      assistantMessage,
      activeConversationId,
      chatContextUsage,
      agentPendingApproval,
      answerStarted: !TRANSIENT_ASSISTANT_TEXTS.has(String(assistantMessage.text || "")),
      normalizeContextUsage,
      getTaskById,
      upsertTaskRecord,
      upsertToolUseRecord,
      upsertApprovalRecord,
      appendTaskEventRecord,
      pushAgentActivity,
      scrollChatToBottom,
    });

    await consumeSseResponse(response, reducer.handleEvent);
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
    hasVisibleTaskActivity,
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

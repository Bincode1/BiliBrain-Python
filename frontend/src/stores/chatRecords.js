import {
  normalizeApproval,
  normalizeTask,
  normalizeTaskEvent,
  normalizeToolUse,
} from "@/utils/chat";

function normalizedId(value) {
  return String(value || "").trim();
}

function newClientId() {
  return `${Date.now()}-${Math.random().toString(16).slice(2, 8)}`;
}

export function createChatRecords({
  activeConversationId,
  chatTasks,
  chatToolUses,
  chatApprovals,
  chatTaskEvents,
}) {
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
    if (!normalized.event_id) normalized.event_id = newClientId();
    chatTaskEvents.value = [...chatTaskEvents.value, normalized];
    return normalized;
  }

  function getTaskById(taskId = null) {
    const taskIdText = normalizedId(taskId);
    if (!taskIdText) return null;
    return chatTasks.value.find((item) => normalizedId(item.task_id) === taskIdText) || null;
  }

  function getToolUseById(toolUseId = null) {
    const toolUseIdText = normalizedId(toolUseId);
    if (!toolUseIdText) return null;
    return chatToolUses.value.find((item) => normalizedId(item.tool_use_id) === toolUseIdText) || null;
  }

  function getApprovalById(approvalId = null) {
    const approvalIdText = normalizedId(approvalId);
    if (!approvalIdText) return null;
    return chatApprovals.value.find((item) => normalizedId(item.approval_id) === approvalIdText) || null;
  }

  function getToolUsesByTaskId(taskId = null) {
    const taskIdText = normalizedId(taskId);
    if (!taskIdText) return [];
    return chatToolUses.value.filter((item) => normalizedId(item.task_id) === taskIdText);
  }

  function getApprovalsByTaskId(taskId = null) {
    const taskIdText = normalizedId(taskId);
    if (!taskIdText) return [];
    return chatApprovals.value.filter((item) => normalizedId(item.task_id) === taskIdText);
  }

  function getLatestApprovalByToolUseId(taskId = null, toolUseId = null) {
    const taskIdText = normalizedId(taskId);
    const toolUseIdText = normalizedId(toolUseId);
    if (!taskIdText || !toolUseIdText) return null;
    return getApprovalsByTaskId(taskIdText)
      .filter((item) => normalizedId(item.tool_use_id) === toolUseIdText)
      .sort((a, b) => String(b.updated_at || b.created_at || "").localeCompare(String(a.updated_at || a.created_at || "")))[0] || null;
  }

  function getTaskEventsByTaskId(taskId = null) {
    const taskIdText = normalizedId(taskId);
    if (!taskIdText) return [];
    return chatTaskEvents.value.filter((item) => normalizedId(item.task_id) === taskIdText);
  }

  function upsertTaskRecord(item) {
    const taskId = normalizedId(item?.task_id);
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
    const toolUseId = normalizedId(item?.tool_use_id);
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
    const approvalId = normalizedId(item?.approval_id);
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

  function hasVisibleTaskActivity(taskId = null) {
    const bundle = getTaskBundle(taskId);
    return !!(
      bundle.toolUses.length
      || bundle.approvals.length
      || bundle.taskEvents.some((item) => normalizedId(item?.event_type) === "command_failed")
    );
  }

  return {
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
  };
}

export function createChatEventReducer({
  assistantMessage,
  activeConversationId,
  chatContextUsage,
  agentPendingApproval,
  answerStarted,
  normalizeContextUsage,
  getTaskById,
  upsertTaskRecord,
  upsertToolUseRecord,
  upsertApprovalRecord,
  appendTaskEventRecord,
  pushAgentActivity,
  scrollChatToBottom,
}) {
  let hasAnswerStarted = answerStarted;

  async function handleEvent({ event, data }) {
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
      if (!hasAnswerStarted) {
        assistantMessage.text = data.delta || "";
        hasAnswerStarted = true;
      } else {
        assistantMessage.text += data.delta || "";
      }
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

  return { handleEvent };
}

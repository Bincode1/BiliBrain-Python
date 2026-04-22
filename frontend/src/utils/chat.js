import { marked } from "marked";

const ESCAPE_MAP = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
function escapeHtml(value) {
  return String(value || "").replace(/[&<>"']/g, (ch) => ESCAPE_MAP[ch]);
}

function buildSourceMap(sources) {
  return new Map(
    sources
      .map((s) => [Number(s.ref_index), s])
      .filter(([i]) => Number.isFinite(i) && i > 0)
  );
}

function renderCitationAnchor(index, sourceMap) {
  const source = sourceMap.get(index);
  if (!source?.jump_url) return null;
  const label = `资料 ${index}`;
  const titleBase = source.title || source.video_title || "资料";
  const title = `${titleBase} ${source.timestamp ? `· ${source.timestamp}` : ""}`;
  return `<a class="inline-citation" href="${escapeHtml(source.jump_url)}" target="_blank" rel="noreferrer" title="${escapeHtml(title)}">${escapeHtml(label)}</a>`;
}

function renderCitationMarkdown(index, sourceMap) {
  const source = sourceMap.get(index);
  if (!source?.jump_url) return null;
  return `[资料 ${index}](${String(source.jump_url).trim()})`;
}

/**
 * 在原始文本上预处理引用格式，将 LLM 输出的各种引用标记统一为 [N]。
 * 这必须在 marked.parse() 之前执行，避免在 HTML 层做正则导致双重嵌套。
 * 逻辑与后端 normalize_answer_citations() 保持一致。
 */
export function normalizeRawCitations(text) {
  if (!text) return "";
  let s = text;
  // (资料1)(资料[1])(资料[1][3]) → [1] 或 [1][3]
  s = s.replace(
    /[（(]\s*资料\s*((?:\[\d+\]\s*(?:[、，,]\s*\[\d+\]\s*)*))[\s）)]/g,
    (match, inner) => {
      const indices = [...inner.matchAll(/\d+/g)].map((m) => `[${m[0]}]`);
      return indices.length ? indices.join("") : match;
    }
  );
  // 资料[N] → [N]
  s = s.replace(/资料\s*\[(\d+)\]/g, "[$1]");
  // 资料 N → [N]
  s = s.replace(/资料\s*(\d+)/g, "[$1]");
  // 【N】 → [N]
  s = s.replace(/【(\d+)】/g, "[$1]");
  return s;
}

function replaceCitationLinks(html, sourceMap) {
  return html.replace(
    /\[(\d+)\]/g,
    (_, idx) => {
      const anchor = renderCitationAnchor(Number(idx), sourceMap);
      return anchor != null ? anchor : `[${idx}]`;
    }
  );
}

export function renderMarkdown(text, sources = []) {
  if (!text) return "";
  const normalized = normalizeRawCitations(String(text));
  const html = marked.parse(normalized);
  if (!Array.isArray(sources) || !sources.length) return html;
  const sourceMap = buildSourceMap(sources);
  return replaceCitationLinks(html, sourceMap);
}

export function renderMessageMarkdown(text, sources = []) {
  if (!text) return "";
  const normalized = normalizeRawCitations(String(text));
  if (!Array.isArray(sources) || !sources.length) return normalized;
  const sourceMap = buildSourceMap(sources);
  return normalized.replace(/\[(\d+)\]/g, (_, idx) => {
    const markdownLink = renderCitationMarkdown(Number(idx), sourceMap);
    return markdownLink != null ? markdownLink : `[${idx}]`;
  });
}

export function splitMessageCitations(text, sources = []) {
  const normalized = normalizeRawCitations(String(text || ""));
  const sourceMap = buildSourceMap(Array.isArray(sources) ? sources : []);
  const parts = [];
  const regex = /\[(\d+)\]/g;
  let lastIndex = 0;
  let match;

  while ((match = regex.exec(normalized)) !== null) {
    const start = match.index;
    if (start > lastIndex) {
      parts.push({ type: "text", value: normalized.slice(lastIndex, start) });
    }
    const refIndex = Number(match[1]);
    const source = sourceMap.get(refIndex);
    if (source) {
      parts.push({ type: "citation", refIndex, source });
    } else {
      parts.push({ type: "text", value: match[0] });
    }
    lastIndex = regex.lastIndex;
  }

  if (lastIndex < normalized.length) {
    parts.push({ type: "text", value: normalized.slice(lastIndex) });
  }

  return parts;
}

export function replaceCitations(html, sources = []) {
  if (!html || !Array.isArray(sources) || !sources.length) return html;
  const sourceMap = buildSourceMap(sources);
  return replaceCitationLinks(html, sourceMap);
}

export function normalizeChatMessage(message, fallbackConversationId = null) {
  return {
    message_id: message.message_id || null,
    conversation_id: message.conversation_id || fallbackConversationId || null,
    task_id: message.task_id || null,
    role: message.role === "assistant" ? "assistant" : "user",
    message_kind: message.message_kind || "default",
    text: message.text ?? message.content ?? "",
    answer_mode: message.answer_mode || null,
    route_mode: message.route_mode || null,
    sources: Array.isArray(message.sources)
      ? message.sources.map((source, index) => ({
          ...source,
          ref_index: Number(source.ref_index || index + 1),
        }))
      : [],
    sourcesExpanded: Boolean(message.sourcesExpanded),
    created_at: message.created_at || "",
    agent_status: message.agent_status || "",
    agent_events: Array.isArray(message.agent_events) ? message.agent_events : [],
    research_plan: message.research_plan || null,
    tool_events: Array.isArray(message.tool_events) ? message.tool_events : [],
    skill_events: Array.isArray(message.skill_events) ? message.skill_events : [],
    active_skills: Array.isArray(message.active_skills) ? message.active_skills : [],
    loaded_skills: Array.isArray(message.loaded_skills) ? message.loaded_skills : [],
    reasoning_text: message.reasoning_text || "",
  };
}

export function sourcePreviewTitle(source) {
  const title = String(source?.video_title || source?.title || source?.domain || "").trim();
  return title.length > 20 ? `${title.slice(0, 20)}…` : title;
}

export function messageModeLabel(message) {
  if (message.answer_mode === "summary") return "摘要回答";
  if (message.answer_mode === "chunk") return "检索回答";
  if (message.answer_mode === "research") return "深度研究";
  if (message.answer_mode === "research_direct") return "研究速答";
  return "";
}

export function messageRouteLabel(message) {
  if (message.route_mode === "direct") return "直接回答";
  if (message.route_mode === "kb_qa") return "知识库问答";
  if (message.route_mode === "research") return "深度研究";
  return "";
}

export function messageSourceKind(message) {
  const kinds = new Set(
    (Array.isArray(message?.sources) ? message.sources : [])
      .map((item) => String(item?.source_kind || "").trim())
      .filter(Boolean)
  );
  if (kinds.size > 1) return "mixed";
  const firstSource = Array.isArray(message?.sources) ? message.sources[0] : null;
  if (firstSource?.source_kind === "web") return "web";
  return firstSource?.source_kind === "summary" ? "summary" : "chunk";
}

export function messageSourceLabel(message) {
  if (messageSourceKind(message) === "summary") return "摘要来源";
  if (messageSourceKind(message) === "web") return "网页来源";
  if (messageSourceKind(message) === "mixed") return "综合来源";
  return "片段来源";
}

export function sourceMetaLabel(source) {
  if (source?.source_kind === "summary") return `视频摘要 · ${source.up_name || "未知 UP"}`;
  if (source?.source_kind === "web") return `${source.domain || "网页"} · ${source.provider || "web"}`;
  return `${source.timestamp || "片段"} · ${source.up_name || "未知 UP"}`;
}

export function normalizeConversation(conversation) {
  return {
    conversation_id: conversation.conversation_id || null,
    folder_id: conversation.folder_id ?? null,
    title: conversation.title || "",
    message_count: Number(conversation.message_count || 0),
    created_at: conversation.created_at || "",
    updated_at: conversation.updated_at || "",
  };
}

export function normalizeTask(task, fallbackConversationId = null) {
  return {
    task_id: task.task_id || null,
    conversation_id: task.conversation_id || fallbackConversationId || null,
    user_message_id: task.user_message_id || null,
    assistant_message_id: task.assistant_message_id || null,
    status: task.status || "queued",
    phase: task.phase || "preparing",
    route_mode: task.route_mode || null,
    answer_mode: task.answer_mode || null,
    pending_tool_use_id: task.pending_tool_use_id || null,
    retry_count: Number(task.retry_count || 0),
    failure_reason: task.failure_reason || "",
    metadata: task.metadata && typeof task.metadata === "object" ? task.metadata : {},
    created_at: task.created_at || "",
    updated_at: task.updated_at || "",
    completed_at: task.completed_at || "",
  };
}

export function normalizeToolUse(toolUse) {
  return {
    tool_use_id: toolUse.tool_use_id || null,
    task_id: toolUse.task_id || null,
    tool_name: toolUse.tool_name || "",
    status: toolUse.status || "pending",
    input_summary: toolUse.input_summary && typeof toolUse.input_summary === "object" ? toolUse.input_summary : {},
    raw_input: toolUse.raw_input && typeof toolUse.raw_input === "object" ? toolUse.raw_input : {},
    raw_output: toolUse.raw_output === undefined ? null : toolUse.raw_output,
    error:
      toolUse.error == null
        ? null
        : typeof toolUse.error === "object"
          ? toolUse.error
          : { message: String(toolUse.error) },
    request_id: toolUse.request_id || null,
    started_at: toolUse.started_at || "",
    finished_at: toolUse.finished_at || "",
    updated_at: toolUse.updated_at || "",
  };
}

export function normalizeApproval(approval) {
  return {
    approval_id: approval.approval_id || null,
    task_id: approval.task_id || null,
    tool_use_id: approval.tool_use_id || null,
    status: approval.status || "pending",
    request_payload: approval.request_payload && typeof approval.request_payload === "object" ? approval.request_payload : {},
    decision_payload: approval.decision_payload && typeof approval.decision_payload === "object" ? approval.decision_payload : null,
    created_at: approval.created_at || "",
    resolved_at: approval.resolved_at || "",
    updated_at: approval.updated_at || "",
  };
}

export function normalizeTaskEvent(taskEvent) {
  return {
    event_id: taskEvent.event_id || null,
    task_id: taskEvent.task_id || null,
    tool_use_id: taskEvent.tool_use_id || null,
    event_type: taskEvent.event_type || "",
    payload: taskEvent.payload && typeof taskEvent.payload === "object" ? taskEvent.payload : {},
    created_at: taskEvent.created_at || "",
  };
}

export function conversationLabel(conversation, index = 0) {
  const title = String(conversation?.title || "").trim();
  if (title) return title;
  return `新对话 ${index + 1}`;
}

export function conversationShortLabel(conversation, index = 0) {
  const label = conversationLabel(conversation, index);
  return label.length > 18 ? `${label.slice(0, 18)}…` : label;
}

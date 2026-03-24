import { marked } from "marked";

function escapeHtml(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

export function renderMarkdown(text, sources = []) {
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

export function normalizeChatMessage(message, fallbackConversationId = null) {
  return {
    message_id: message.message_id || null,
    conversation_id: message.conversation_id || fallbackConversationId || null,
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

export function sourcePreviewTitle(source) {
  const title = String(source?.video_title || "").trim();
  return title.length > 20 ? `${title.slice(0, 20)}…` : title;
}

export function messageModeLabel(message) {
  if (message.answer_mode === "summary") {
    return "摘要回答";
  }
  if (message.answer_mode === "chunk") {
    return "检索回答";
  }
  return "";
}

export function messageSourceKind(message) {
  const firstSource = Array.isArray(message?.sources) ? message.sources[0] : null;
  return firstSource?.source_kind === "summary" ? "summary" : "chunk";
}

export function messageSourceLabel(message) {
  return messageSourceKind(message) === "summary" ? "摘要来源" : "片段来源";
}

export function sourceMetaLabel(source) {
  if (source?.source_kind === "summary") {
    return `视频摘要 · ${source.up_name || "未知 UP"}`;
  }
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

export function conversationLabel(conversation, index = 0) {
  const title = String(conversation?.title || "").trim();
  if (title) {
    return title;
  }
  return `新对话 ${index + 1}`;
}

export function conversationShortLabel(conversation, index = 0) {
  const label = conversationLabel(conversation, index);
  return label.length > 18 ? `${label.slice(0, 18)}…` : label;
}

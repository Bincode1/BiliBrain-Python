import { marked } from "marked";

function escapeHtml(value) {
  const div = document.createElement("div");
  div.textContent = value || "";
  return div.innerHTML;
}

export function renderMarkdown(text, sources = []) {
  if (!text) return "";
  const markdownText = String(text);
  if (!Array.isArray(sources) || !sources.length) {
    return marked.parse(markdownText);
  }
  const sourceMap = new Map(
    sources
      .map((source) => [Number(source.ref_index), source])
      .filter(([index]) => Number.isFinite(index) && index > 0)
  );

  function renderCitationAnchor(rawIndex) {
    const index = Number(rawIndex);
    const source = sourceMap.get(index);
    if (!source?.jump_url) {
      return null;
    }
    const label = `资料 ${index}`;
    const titleBase = source.title || source.video_title || "资料";
    const title = `${titleBase} ${source.timestamp ? `· ${source.timestamp}` : ""}`;
    return `<a class="inline-citation" href="${escapeHtml(source.jump_url)}" target="_blank" rel="noreferrer" title="${escapeHtml(title)}">${escapeHtml(label)}</a>`;
  }

  return marked.parse(markdownText).replace(/【(\d+)】/g, (_, rawIndex) => {
    return renderCitationAnchor(rawIndex) || `【${rawIndex}】`;
  });
}

export function parseTextSegments(rawText, sources = []) {
  if (!rawText) return [];

  const segments = [];
  let currentText = "";
  let i = 0;

  const sourceMap = new Map(
    sources
      .map((source) => [Number(source.ref_index), source])
      .filter(([index]) => Number.isFinite(index) && index > 0)
  );

  while (i < rawText.length) {
    if (rawText[i] === "【") {
      if (currentText) {
        segments.push({ type: "text", content: currentText });
        currentText = "";
      }

      let j = i + 1;
      let numStr = "";
      while (j < rawText.length && j < i + 10) {
        if (/\d/.test(rawText[j])) {
          numStr += rawText[j];
          j++;
        } else {
          break;
        }
      }

      if (j < rawText.length && rawText[j] === "】" && numStr.length > 0) {
        const index = Number(numStr);
        const source = sourceMap.get(index);
        if (source?.jump_url) {
          const titleBase = source.title || source.video_title || "资料";
          segments.push({
            type: "citation",
            index,
            label: `资料 ${index}`,
            title: `${titleBase} ${source.timestamp ? `· ${source.timestamp}` : ""}`,
            url: source.jump_url,
          });
        } else {
          segments.push({ type: "text", content: `【${numStr}】` });
        }
        i = j + 1;
      } else {
        currentText += "【";
        i++;
      }
    } else {
      currentText += rawText[i];
      i++;
    }
  }

  if (currentText) {
    segments.push({ type: "text", content: currentText });
  }

  return segments;
}

export function renderSegmentsToHtml(segments) {
  return segments
    .map((seg) => {
      if (seg.type === "text") {
        return escapeHtml(seg.content);
      }
      if (seg.type === "citation") {
        return `<a class="inline-citation" href="${escapeHtml(seg.url)}" target="_blank" rel="noreferrer" title="${escapeHtml(seg.title)}">${escapeHtml(seg.label)}</a>`;
      }
      return "";
    })
    .join("");
}

export function normalizeChatMessage(message, fallbackConversationId = null) {
  return {
    message_id: message.message_id || null,
    conversation_id: message.conversation_id || fallbackConversationId || null,
    role: message.role === "assistant" ? "assistant" : "user",
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
  };
}

export function sourcePreviewTitle(source) {
  const title = String(source?.video_title || source?.title || source?.domain || "").trim();
  return title.length > 20 ? `${title.slice(0, 20)}…` : title;
}

export function messageModeLabel(message) {
  if (message.answer_mode === "summary") {
    return "摘要回答";
  }
  if (message.answer_mode === "chunk") {
    return "检索回答";
  }
  if (message.answer_mode === "research") {
    return "深度研究";
  }
  return "";
}

export function messageRouteLabel(message) {
  if (message.route_mode === "history_only") {
    return "会话回顾";
  }
  if (message.route_mode === "summary_only") {
    return "总结路由";
  }
  if (message.route_mode === "chunk_only") {
    return "检索路由";
  }
  if (message.route_mode === "mixed") {
    return "混合路由";
  }
  if (message.route_mode === "research") {
    return "研究路由";
  }
  return "";
}

export function messageSourceKind(message) {
  const kinds = new Set(
    (Array.isArray(message?.sources) ? message.sources : [])
      .map((item) => String(item?.source_kind || "").trim())
      .filter(Boolean)
  );
  if (kinds.size > 1) {
    return "mixed";
  }
  const firstSource = Array.isArray(message?.sources) ? message.sources[0] : null;
  if (firstSource?.source_kind === "web") {
    return "web";
  }
  return firstSource?.source_kind === "summary" ? "summary" : "chunk";
}

export function messageSourceLabel(message) {
  if (messageSourceKind(message) === "summary") {
    return "摘要来源";
  }
  if (messageSourceKind(message) === "web") {
    return "网页来源";
  }
  if (messageSourceKind(message) === "mixed") {
    return "综合来源";
  }
  return "片段来源";
}

export function sourceMetaLabel(source) {
  if (source?.source_kind === "summary") {
    return `视频摘要 · ${source.up_name || "未知 UP"}`;
  }
  if (source?.source_kind === "web") {
    return `${source.domain || "网页"} · ${source.provider || "web"}`;
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

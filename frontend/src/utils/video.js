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
const SYNC_STATUS_LABELS = {
  pending: "待处理",
  processing: "处理中",
  indexed: "已入库",
  failed: "失败",
  partial: "部分完成",
};

export function formatDuration(seconds) {
  const total = Number(seconds || 0);
  const minutes = Math.floor(total / 60);
  const remain = total % 60;
  return `${String(minutes).padStart(2, "0")}:${String(remain).padStart(2, "0")}`;
}

export function buildStepItems(pipeline) {
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

export function actionLabelFromStatus(status) {
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

export function syncStatusLabel(status) {
  return SYNC_STATUS_LABELS[String(status || "").trim()] || String(status || "待处理");
}

export function normalizeCoverUrl(url) {
  const raw = String(url || "").trim();
  if (!raw) {
    return "";
  }
  if (raw.startsWith("//")) {
    return `https:${raw}`;
  }
  return raw;
}

export function videoWatchUrl(video) {
  if (!video || video.is_invalid || !video.bvid || String(video.bvid).startsWith("invalid:")) {
    return "";
  }
  return `https://www.bilibili.com/video/${encodeURIComponent(video.bvid)}/`;
}

export function openVideoLink(video) {
  const url = videoWatchUrl(video);
  if (!url) {
    return;
  }
  window.open(url, "_blank", "noopener,noreferrer");
}

function normalizeSearchText(value) {
  return String(value || "")
    .toLowerCase()
    .replace(/\s+/g, " ")
    .trim();
}

function tokenizeSearchQuery(query) {
  const normalized = normalizeSearchText(query);
  if (!normalized) {
    return [];
  }
  return normalized.split(/[\s,，、]+/).filter(Boolean);
}

export function searchVideos(videos, query, options = {}) {
  const normalizedQuery = normalizeSearchText(query);
  if (!normalizedQuery) {
    return [];
  }

  const limit = Number(options.limit || 0) > 0 ? Number(options.limit) : Number.POSITIVE_INFINITY;
  const tokens = tokenizeSearchQuery(normalizedQuery);

  return (videos || [])
    .map((video, index) => {
      const title = normalizeSearchText(video?.title);
      const upName = normalizeSearchText(video?.up_name);
      const tags = normalizeSearchText(Array.isArray(video?.manual_tags) ? video.manual_tags.join(" ") : "");
      const bvid = normalizeSearchText(video?.bvid);

      let score = 0;
      if (title.includes(normalizedQuery)) score += 120;
      if (upName.includes(normalizedQuery)) score += 48;
      if (tags.includes(normalizedQuery)) score += 72;
      if (bvid.includes(normalizedQuery)) score += 56;

      for (const token of tokens) {
        let matched = false;
        if (title.includes(token)) {
          score += title.startsWith(token) ? 34 : 24;
          matched = true;
        }
        if (tags.includes(token)) {
          score += 18;
          matched = true;
        }
        if (upName.includes(token)) {
          score += 14;
          matched = true;
        }
        if (bvid.includes(token)) {
          score += 12;
          matched = true;
        }
        if (!matched) {
          score = 0;
          break;
        }
      }

      return { index, score, video };
    })
    .filter((item) => item.score > 0)
    .sort((left, right) => {
      if (right.score !== left.score) {
        return right.score - left.score;
      }
      return left.index - right.index;
    })
    .slice(0, limit)
    .map((item) => item.video);
}

export function decorateVideo(video) {
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
    resetBusy: false,
  };
}

export function decorateFolder(folder) {
  return {
    ...folder,
    expanded: false,
    loadingVideos: false,
    videoError: "",
    fields: [],
    videos: [],
  };
}

export function firstSelectableVideo(videos) {
  return (videos || []).find((video) => !video.is_invalid) || null;
}

export function hasTranscript(video) {
  return Boolean(video && (Number(video.transcript_segment_count || 0) > 0 || video.transcript_updated_at));
}

export function canOpenSummary(video) {
  return Boolean(video?.has_summary);
}

export function canGenerateSummary(video) {
  return Boolean(video && hasTranscript(video) && !video.has_summary && !video.summaryBusy);
}

export function canOpenTranscript(video) {
  return hasTranscript(video);
}

export function summaryStateTone(video) {
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

export function summaryStateLabel(video) {
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

export function applyProcessStatus(video, status, fallbackMaxVideoMinutes) {
  const operation = status.operation || null;
  video.sync_status = status.overall_status;
  video.chunk_count = Number(status.chunk_count || 0);
  video.error_msg = status.error_msg || "";
  video.transcript_source = status.transcript_source || "未转写";
  video.transcript_segment_count = Number(status.transcript_segment_count || 0);
  video.transcript_updated_at = status.transcript_updated_at || "";
  video.has_summary = Boolean(status.has_summary);
  video.summary_updated_at = status.summary_updated_at || "";
  video.audio_storage_provider = status.audio_storage_provider || video.audio_storage_provider || null;
  video.audio_object_key = status.audio_object_key || video.audio_object_key || null;
  video.manual_tags = Array.isArray(status.manual_tags) ? status.manual_tags : [];
  video.manualTagsInput = video.manual_tags.join(", ");
  video.steps = Array.isArray(status.steps) ? status.steps : video.steps;
  video.processActionLabel = status.action_label || "开始处理";
  video.over_limit = Boolean(status.over_limit);
  video.max_video_minutes = Number(status.max_video_minutes || fallbackMaxVideoMinutes);
  video.processBusy = Boolean(status.running && operation === "process");
  video.resetBusy = Boolean(status.reset_running || (status.running && operation === "reset"));
}

export function resetVideoProcessState(video, fallbackMaxVideoMinutes) {
  const hasRetainedAudio = Boolean(video.audio_storage_provider && video.audio_object_key);
  video.sync_status = "pending";
  video.chunk_count = 0;
  video.error_msg = "";
  video.transcript_source = "未转写";
  video.transcript_segment_count = 0;
  video.transcript_updated_at = "";
  video.has_summary = false;
  video.summary_updated_at = "";
  video.steps = buildStepItems(
    hasRetainedAudio
      ? {
          audio: {
            status: "done",
            status_label: STATUS_LABELS.done,
          },
        }
      : {}
  );
  video.processActionLabel = actionLabelFromStatus("pending");
  video.processBusy = false;
  video.resetBusy = false;
  video.summaryBusy = false;
  video.max_video_minutes = Number(video.max_video_minutes || fallbackMaxVideoMinutes);
}

export function videoTone(video) {
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

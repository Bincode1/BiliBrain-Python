import { prepare, layout } from "@chenglou/pretext";

/**
 * Pretext 高度测量服务。
 *
 * 使用 Pretext 在纯算术层计算文本段落高度（不碰 DOM），
 * 并叠加块级 Markdown 元素修正值。
 */

// 块级元素修正值（px）
const BLOCK_CORRECTIONS = {
  pre: 22, // padding-top 10px + padding-bottom 10px + margin-bottom 2px
  ul: 12,
  ol: 12,
  h1: 14,
  h2: 12,
  h3: 10,
  blockquote: 16,
  table: 10,
};

// 非文本部分的固定高度估算
const PART_HEIGHTS = {
  messageHead: 28,
  messageGap: 10,
  agentEventItem: 28,
  agentPanelBase: 40,
  sourcePanelCollapsed: 44,
  sourcePanelExpanded: 60,
  sourceItem: 36,
};

/**
 * 创建 Pretext 高度测量服务实例。
 *
 * @param {object} options
 * @param {HTMLElement} options.containerEl - 聊天容器元素，用于测量容器宽度
 * @param {string} options.bodySelector - 消息正文 CSS 选择器，用于推导字体
 */
export function createPretextHeightService({ containerEl, bodySelector = ".message.assistant .message-body" } = {}) {
  let fontShorthand = "13px sans-serif";
  let lineHeightValue = 22.75; // 13px * 1.75
  let maxWidth = 600;
  let paddingH = 40; // 消息正文左右 padding 之和

  // PreparedText 缓存：key = text content hash -> { prepared, textLen }
  const cache = new Map();
  const MAX_CACHE_SIZE = 200;

  // ---------- 初始化字体参数 ----------

  function initFont() {
    try {
      const probe = document.createElement("div");
      probe.className = "message-body";
      probe.style.cssText =
        "position:absolute;visibility:hidden;pointer-events:none;left:-9999px;";
      probe.textContent = "Probe测";
      document.body.appendChild(probe);
      const cs = getComputedStyle(probe);
      const fontSize = parseFloat(cs.fontSize) || 13;
      const lineHeight = parseFloat(cs.lineHeight) || fontSize * 1.75;
      const fontStyle = cs.fontStyle || "normal";
      const fontWeight = cs.fontWeight || "400";
      const fontFamily = cs.fontFamily || "sans-serif";
      fontShorthand = `${fontStyle} ${fontWeight} ${fontSize}px ${fontFamily}`;
      lineHeightValue = lineHeight;
      paddingH =
        parseFloat(cs.paddingLeft || 0) + parseFloat(cs.paddingRight || 0);
      probe.remove();
    } catch {
      // fallback 保留默认值
    }
  }

  function updateContainerWidth() {
    if (!containerEl) return;
    const cs = getComputedStyle(containerEl);
    const containerPadding =
      parseFloat(cs.paddingLeft || 0) + parseFloat(cs.paddingRight || 0);
    maxWidth = containerEl.clientWidth - containerPadding - paddingH;
    if (maxWidth < 100) maxWidth = 300;
    invalidateAll();
  }

  function invalidateAll() {
    cache.clear();
  }

  // ---------- 核心测量 ----------

  function measureBodyHeight(rawText) {
    if (!rawText) return 0;

    const cacheKey = rawText.length + ":" + rawText.slice(0, 64);
    const cached = cache.get(cacheKey);
    if (cached && cached.textLen === rawText.length) {
      return layout(cached.prepared, maxWidth, lineHeightValue).height;
    }

    // 清理过大缓存
    if (cache.size > MAX_CACHE_SIZE) {
      const keys = [...cache.keys()];
      for (let i = 0; i < keys.length >> 1; i++) cache.delete(keys[i]);
    }

    const prepared = prepare(rawText, fontShorthand);
    cache.set(cacheKey, { prepared, textLen: rawText.length });
    return layout(prepared, maxWidth, lineHeightValue).height;
  }

  /**
   * 计算 Markdown 块级元素修正值。
   * 扫描已渲染的 HTML，统计特殊块的数量。
   */
  function computeBlockCorrection(html) {
    if (!html) return 0;
    let correction = 0;
    for (const [tag, px] of Object.entries(BLOCK_CORRECTIONS)) {
      const re = new RegExp(`<${tag}[\\s>]`, "g");
      const count = (html.match(re) || []).length;
      correction += count * px;
    }
    return correction;
  }

  /**
   * 测量单条消息的总高度。
   *
   * @param {object} message - 标准化后的消息对象
   * @param {string|null} stableHtml - 增量解析器产出的稳定 HTML（可选）
   * @returns {number} 估算高度（px）
   */
  function measureMessageHeight(message, stableHtml = null) {
    const rawText = message.text || "";
    const textHeight = measureBodyHeight(rawText);

    // 块级修正
    const htmlForCorrection = stableHtml || rawText;
    const correction = computeBlockCorrection(htmlForCorrection);

    let height = textHeight + correction;

    // message-head
    height += PART_HEIGHTS.messageHead + PART_HEIGHTS.messageGap;

    // agent-activity-panel
    const agentEvents = message.agent_events || [];
    const skillEvents = message.skill_events || [];
    const toolEvents = message.tool_events || [];
    const totalAgentItems =
      agentEvents.length + skillEvents.length + toolEvents.length;
    if (totalAgentItems > 0 || message.agent_status || message.research_plan) {
      height +=
        PART_HEIGHTS.agentPanelBase +
        totalAgentItems * PART_HEIGHTS.agentEventItem;
    }

    // source-panel
    const sources = message.sources || [];
    if (sources.length > 0) {
      if (message.sourcesExpanded) {
        height +=
          PART_HEIGHTS.sourcePanelExpanded +
          sources.length * PART_HEIGHTS.sourceItem;
      } else {
        height += PART_HEIGHTS.sourcePanelCollapsed;
      }
    }

    // chat-stream gap
    height += 18;

    return Math.max(height, 40);
  }

  // ---------- 生命周期 ----------

  function init(el) {
    containerEl = el;
    initFont();
    updateContainerWidth();
  }

  function dispose() {
    cache.clear();
    containerEl = null;
  }

  return {
    init,
    measureBodyHeight,
    measureMessageHeight,
    computeBlockCorrection,
    updateContainerWidth,
    invalidateAll,
    dispose,
  };
}

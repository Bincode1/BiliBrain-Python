import { ref, computed, watch, onUnmounted, nextTick } from "vue";
import { createPretextHeightService } from "@/utils/pretextHeight";

const BUFFER_SIZE = 3;
const HEIGHT_CORRECTION_THRESHOLD = 5;

/**
 * 虚拟滚动 composable。
 *
 * 基于 Pretext 预算的消息高度，只渲染可视区域内的消息 DOM。
 * 渲染后通过实际 DOM 高度修正 Pretext 误差。
 */
export function useVirtualScroll({ items, containerRef }) {
  const heightService = createPretextHeightService();

  // 每条消息的缓存高度
  const itemHeights = ref([]);
  // 可视范围
  const startIndex = ref(0);
  const endIndex = ref(0);

  let scrollRafId = null;
  let active = true;

  // ---------- 初始化高度 ----------

  function computeAllHeights() {
    const msgs = items.value;
    if (!msgs.length) {
      itemHeights.value = [];
      return;
    }
    const heights = new Array(msgs.length);
    for (let i = 0; i < msgs.length; i++) {
      heights[i] = computeMessageHeight(msgs[i], i);
    }
    itemHeights.value = heights;
  }

  function computeMessageHeight(message, index) {
    // 增量渲染中的消息用 _stableHtml 做块级修正
    const stableHtml = message._stableHtml || null;
    const h = heightService.measureMessageHeight(message, stableHtml);
    return Math.max(h, 40);
  }

  // ---------- 累积高度 ----------

  const cumHeights = computed(() => {
    const heights = itemHeights.value;
    const cum = new Array(heights.length);
    let sum = 0;
    for (let i = 0; i < heights.length; i++) {
      sum += heights[i];
      cum[i] = sum;
    }
    return cum;
  });

  const totalHeight = computed(() => {
    const ch = cumHeights.value;
    return ch.length ? ch[ch.length - 1] : 0;
  });

  // ---------- 二分查找 ----------

  /** 找到第一个 arr[i] >= target 的索引 (O(log n)) */
  function bisectLeft(arr, target, lo = 0) {
    let hi = arr.length;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (arr[mid] < target) lo = mid + 1;
      else hi = mid;
    }
    return Math.min(lo, arr.length - 1);
  }

  // ---------- 可视范围计算 ----------

  function computeVisibleRange() {
    const el = containerRef.value;
    if (!el || !active) return;

    const scrollTop = el.scrollTop;
    const viewportHeight = el.clientHeight;
    const ch = cumHeights.value;
    const len = ch.length;

    if (!len) {
      startIndex.value = 0;
      endIndex.value = 0;
      return;
    }

    const topBoundary = Math.max(0, scrollTop - 0);
    const bottomBoundary = scrollTop + viewportHeight;

    // 二分查找 startIndex：第一个 cumHeight >= topBoundary (O(log n))
    const s = bisectLeft(ch, topBoundary);
    startIndex.value = Math.max(0, s - BUFFER_SIZE);

    // 二分查找 endIndex：第一个 cumHeight >= bottomBoundary
    const e = bisectLeft(ch, bottomBoundary, Math.max(0, s));
    endIndex.value = Math.min(len - 1, e + BUFFER_SIZE);

    // 最后一条消息（可能在流式输出）始终可见
    if (len > 0) {
      endIndex.value = Math.max(endIndex.value, len - 1);
    }
  }

  // ---------- Scroll 事件 ----------

  function onScroll() {
    if (scrollRafId) return;
    scrollRafId = requestAnimationFrame(() => {
      scrollRafId = null;
      if (!active) return;
      computeVisibleRange();
    });
  }

  // ---------- 消息列表变化时重算 ----------

  watch(
    () => items.value.length,
    () => {
      computeAllHeights();
      computeVisibleRange();
    }
  );

  // 监听消息内容变化（流式输出时 text 增长）
  watch(
    () => {
      const msgs = items.value;
      // 只检查最后一条（流式中的消息）
      if (!msgs.length) return 0;
      const last = msgs[msgs.length - 1];
      return (last.text || "").length;
    },
    () => {
      const msgs = items.value;
      if (!msgs.length) return;
      const lastIdx = msgs.length - 1;
      const heights = [...itemHeights.value];
      // 只重算最后一条
      while (heights.length < msgs.length) heights.push(60);
      heights[lastIdx] = computeMessageHeight(msgs[lastIdx], lastIdx);
      itemHeights.value = heights;
      // 不重新算范围，让下一帧 scroll 事件处理
    }
  );

  // ---------- DOM 高度修正 ----------

  function correctHeightsFromDOM() {
    const el = containerRef.value;
    if (!el) return;

    const msgEls = el.querySelectorAll(".message");
    let changed = false;
    const heights = [...itemHeights.value];

    msgEls.forEach((msgEl) => {
      const idx = parseInt(msgEl.dataset.vtIndex, 10);
      if (isNaN(idx) || idx >= heights.length) return;
      const actual = msgEl.offsetHeight + 18; // 加上 gap
      if (Math.abs(actual - heights[idx]) > HEIGHT_CORRECTION_THRESHOLD) {
        heights[idx] = actual;
        changed = true;
      }
    });

    if (changed) {
      itemHeights.value = heights;
      computeVisibleRange();
    }
  }

  // ---------- 可见消息 ----------

  const visibleMessages = computed(() => {
    const msgs = items.value;
    const s = startIndex.value;
    const e = endIndex.value;
    if (!msgs.length) return [];
    return msgs.slice(s, e + 1).map((msg, i) => ({
      ...msg,
      _vtIndex: s + i,
    }));
  });

  // ---------- Spacers ----------

  const spacerTopStyle = computed(() => {
    const ch = cumHeights.value;
    const s = startIndex.value;
    const top = s > 0 && ch.length >= s ? ch[s - 1] : 0;
    return { height: `${top}px` };
  });

  const spacerBottomStyle = computed(() => {
    const ch = cumHeights.value;
    const e = endIndex.value;
    const total = totalHeight.value;
    const used = e >= 0 && ch.length > e ? ch[e] : 0;
    const bottom = Math.max(0, total - used);
    return { height: `${bottom}px` };
  });

  // ---------- 初始化 ----------

  function init() {
    const el = containerRef.value;
    if (!el) return;
    heightService.init(el);
    el.addEventListener("scroll", onScroll, { passive: true });
    computeAllHeights();
    // 初始滚动到底部
    nextTick(() => {
      computeVisibleRange();
    });
  }

  function forceRecalculate() {
    computeAllHeights();
    computeVisibleRange();
  }

  function dispose() {
    active = false;
    const el = containerRef.value;
    if (el) {
      el.removeEventListener("scroll", onScroll);
    }
    if (scrollRafId) {
      cancelAnimationFrame(scrollRafId);
      scrollRafId = null;
    }
    heightService.dispose();
  }

  onUnmounted(() => {
    dispose();
  });

  return {
    visibleMessages,
    spacerTopStyle,
    spacerBottomStyle,
    forceRecalculate,
    init,
    dispose,
    heightService,
  };
}

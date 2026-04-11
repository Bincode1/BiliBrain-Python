import { ref, onUnmounted } from "vue";

const NEAR_BOTTOM_THRESHOLD = 80;

/**
 * 智能滚动 composable。
 *
 * - RAF 节流的 scroll 事件监听
 * - isNearBottom 检测用户是否在底部附近
 * - scrollToBottomIfNear() 仅在 nearBottom 时自动滚动
 * - showScrollButton 在用户上翻时显示
 */
export function useSmartScroll(containerRef) {
  const isNearBottom = ref(true);
  const showScrollButton = ref(false);

  let rafId = null;
  let pendingScrollTop = 0;
  let hasNewContent = false;
  let active = true;

  function checkNearBottom() {
    const el = containerRef.value;
    if (!el) return true;
    return el.scrollTop + el.clientHeight >= el.scrollHeight - NEAR_BOTTOM_THRESHOLD;
  }

  function onScroll() {
    const el = containerRef.value;
    if (!el) return;
    pendingScrollTop = el.scrollTop;

    if (rafId) return;
    rafId = requestAnimationFrame(() => {
      rafId = null;
      if (!active) return;
      isNearBottom.value = checkNearBottom();
      if (isNearBottom.value) {
        showScrollButton.value = false;
        hasNewContent = false;
      }
    });
  }

  function scrollToBottom() {
    const el = containerRef.value;
    if (!el) return;
    // 直接同步设置，不走 RAF（用户主动触发）
    el.scrollTop = el.scrollHeight;
    isNearBottom.value = true;
    showScrollButton.value = false;
    hasNewContent = false;
  }

  /**
   * 替代旧的 scrollChatToBottom()。
   * 仅在用户靠近底部时自动滚动，否则只标记有新内容。
   */
  function scrollToBottomIfNear() {
    if (!active) return;
    // 先检查当前是否 near bottom（同步读，不触发额外 reflow）
    if (isNearBottom.value) {
      // 用 RAF 合并同一帧内的多次调用
      if (!rafId) {
        rafId = requestAnimationFrame(() => {
          rafId = null;
          scrollToBottom();
        });
      }
    } else {
      hasNewContent = true;
      showScrollButton.value = true;
    }
  }

  /**
   * 内容高度增长时的回调。
   */
  function onContentGrown() {
    if (!active) return;
    if (isNearBottom.value) {
      scrollToBottom();
    }
  }

  function bind() {
    const el = containerRef.value;
    if (el) {
      el.addEventListener("scroll", onScroll, { passive: true });
    }
  }

  function unbind() {
    const el = containerRef.value;
    if (el) {
      el.removeEventListener("scroll", onScroll);
    }
    if (rafId) {
      cancelAnimationFrame(rafId);
      rafId = null;
    }
  }

  function dispose() {
    active = false;
    unbind();
  }

  onUnmounted(() => {
    dispose();
  });

  return {
    isNearBottom,
    showScrollButton,
    scrollToBottom,
    scrollToBottomIfNear,
    onContentGrown,
    bind,
    unbind,
    dispose,
  };
}

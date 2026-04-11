import { marked } from "marked";
import { replaceCitations } from "@/utils/chat";

/**
 * 增量 Markdown 流式解析器。
 *
 * 维护一个 stableBoundary 游标，将累积文本分为：
 *   - stable（已确认边界之前的文本）→ marked.parse() 固化成 HTML
 *   - tail（边界之后的文本）→ 转义为纯文本 + 闪烁光标
 *
 * 边界检测仅在 push(delta) 时增量扫描新增部分，不全量重扫。
 */
export function createStreamParser(sources = []) {
  let text = "";
  let stableBoundary = 0;
  let cachedStableHtml = "";
  let cachedStableText = "";

  // 代码围栏状态
  let inCodeFence = false;
  let codeFenceLength = 0;
  let codeFenceChar = "";

  let finalized = false;

  function escapeHtml(value) {
    return value
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  /**
   * 从 tail 中寻找下一个稳定边界。
   * 只扫描 stableBoundary 之后的文本。
   */
  function advanceBoundary() {
    let tail = text.slice(stableBoundary);

    // Phase 1: 如果在代码围栏内，只找闭合围栏
    if (inCodeFence) {
      const fenceCloseRe = new RegExp(
        `^${escapeRegexChar(codeFenceChar)}{${codeFenceLength},}\\s*$`,
        "m"
      );
      const match = fenceCloseRe.exec(tail);
      if (match) {
        const closeEnd = match.index + match[0].length;
        // 闭合围栏后跟一个 \n 或到末尾
        const afterClose =
          closeEnd < tail.length && tail[closeEnd] === "\n"
            ? closeEnd + 1
            : closeEnd;
        stableBoundary += afterClose;
        inCodeFence = false;
        reparseStable();
        // 继续扫描新的 tail
        advanceBoundary();
      }
      return;
    }

    // Phase 2: 逐行扫描寻找边界
    let pos = 0;
    let lastBoundary = 0;

    while (pos < tail.length) {
      // 检测代码围栏开始（``` 或 ~~~）
      const fenceMatch = tail.slice(pos).match(/^(`{3,}|~{3,})/);
      if (
        fenceMatch &&
        (pos === 0 || tail[pos - 1] === "\n")
      ) {
        codeFenceChar = fenceMatch[1][0];
        codeFenceLength = fenceMatch[1].length;
        inCodeFence = true;
        // 先固化围栏之前的文本
        if (pos > lastBoundary) {
          stableBoundary += pos;
          reparseStable();
        }
        // 然后尝试找闭合围栏（可能在同一 delta 中）
        advanceBoundary();
        return;
      }

      // 检测双换行（段落边界）
      if (tail[pos] === "\n" && pos + 1 < tail.length && tail[pos + 1] === "\n") {
        stableBoundary += pos + 2;
        lastBoundary = pos + 2;
        pos += 2;
        reparseStable();
        tail = text.slice(stableBoundary);
        pos = 0;
        lastBoundary = 0;
        continue;
      }

      // 前进到下一个换行
      const nextNl = tail.indexOf("\n", pos);
      if (nextNl === -1) break;
      pos = nextNl + 1;
    }
  }

  function escapeRegexChar(ch) {
    return ch === "`" ? "`" : ch === "~" ? "~" : ch;
  }

  function reparseStable() {
    const stableText = text.slice(0, stableBoundary);
    if (stableText === cachedStableText) return;
    cachedStableText = stableText;
    cachedStableHtml = stableText
      ? replaceCitations(marked.parse(stableText), sources)
      : "";
  }

  /**
   * 追加一段流式文本增量。
   */
  function push(delta) {
    if (finalized || !delta) return;
    text += delta;
    advanceBoundary();
  }

  /**
   * 获取已稳定的部分（已 parse 的 HTML）。
   */
  function getStable() {
    return {
      html: cachedStableHtml,
      text: cachedStableText,
    };
  }

  /**
   * 获取尾部未稳定部分（转义 HTML + 可选光标）。
   */
  function getTail() {
    const tail = text.slice(stableBoundary);
    if (!tail) {
      return { escapedHtml: "", hasCursor: !finalized };
    }
    const escaped = escapeHtml(tail);
    return {
      escapedHtml: !finalized ? escaped : "",
      hasCursor: !finalized,
    };
  }

  /**
   * 流结束：将剩余 tail 全部 parse。
   */
  function finalize() {
    finalized = true;
    stableBoundary = text.length;
    reparseStable();
  }

  /**
   * 更新引用来源（sources 可能在流结束后才到达）。
   */
  function setSources(newSources) {
    sources = newSources;
    // 重新 parse stable 部分
    cachedStableText = "";
    reparseStable();
  }

  return {
    push,
    getStable,
    getTail,
    finalize,
    setSources,
    get stableBoundary() {
      return stableBoundary;
    },
    get fullText() {
      return text;
    },
  };
}

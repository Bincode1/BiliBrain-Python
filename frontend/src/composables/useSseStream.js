import { shallowRef, onBeforeUnmount } from "vue";
import { parseSseFrames, parseSseEvent } from "@/utils/sse";

/**
 * 统一 SSE 流式处理 composable。
 *
 * 提供单一的 SSE 解析循环，消除 RAG / Agent 路径的代码重复。
 * 内置 AbortController，组件卸载时自动中断连接。
 */
export function useSseStream() {
  const controller = shallowRef(null);

  /**
   * 消费一个 SSE fetch Response。
   *
   * @param {Response} response - 已完成的 fetch Response（必须是 200）
   * @param {Object} handlers - 事件处理器
   * @param {(text: string) => void} [handlers.onToken] - 流式文本增量
   * @param {(sources: Array) => void} [handlers.onSources] - 引用来源
   * @param {(event: Object) => void} [handlers.onAgentStatus] - Agent 状态事件
   * @param {(approval: Object) => void} [handlers.onApproval] - 技能审批请求
   * @param {(data: Object) => void} [handlers.onConversation] - 会话信息
   * @param {(data: Object) => void} [handlers.onRoute] - 路由模式
   * @param {(data: Object) => void} [handlers.onMode] - 回答模式
   * @param {(data: Object) => void} [handlers.onStatus] - 状态更新
   * @param {(data: Object) => void} [handlers.onSkill] - 技能事件
   * @param {(data: Object) => void} [handlers.onTool] - 工具事件
   * @param {(data: Object) => void} [handlers.onSkills] - 技能列表
   * @param {() => void} [handlers.onDone] - 流结束
   * @param {(error: string) => void} [handlers.onError] - 错误
   */
  async function consumeStream(response, handlers = {}) {
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const { frames, rest } = parseSseFrames(buffer);
        buffer = rest;

        for (const frame of frames) {
          const { event, data } = parseSseEvent(frame);
          dispatchEvent(event, data, handlers);
        }
      }

      // 处理 buffer 中可能残留的最后一帧
      if (buffer.trim()) {
        try {
          const { event, data } = parseSseEvent(buffer.trim());
          dispatchEvent(event, data, handlers);
        } catch {
          // 忽略不完整的最后一帧
        }
      }
    } finally {
      handlers.onDone?.();
    }
  }

  function dispatchEvent(event, data, handlers) {
    switch (event) {
      case "conversation":
        handlers.onConversation?.(data);
        break;
      case "route":
        handlers.onRoute?.(data);
        break;
      case "mode":
        handlers.onMode?.(data);
        break;
      case "status":
        handlers.onStatus?.(data);
        break;
      case "answer":
      case "answer_normalized":
        handlers.onToken?.(data.delta || data.text || "");
        break;
      case "sources":
        handlers.onSources?.(data.sources || data);
        break;
      case "agent_status":
        handlers.onAgentStatus?.(data);
        break;
      case "approval":
        handlers.onApproval?.(data);
        break;
      case "skill":
        handlers.onSkill?.(data);
        break;
      case "tool":
        handlers.onTool?.(data);
        break;
      case "skills":
        handlers.onSkills?.(data);
        break;
      case "error":
        handlers.onError?.(data.detail || data.message || "流式处理出错");
        break;
      default:
        // 忽略未知事件
        break;
    }
  }

  function abort() {
    controller.value?.abort();
    controller.value = null;
  }

  /**
   * 创建带 AbortController 的 fetch 请求。
   * @returns {Promise<Response>}
   */
  async function fetchStream(url, body) {
    abort(); // 取消上一个流
    const ctrl = new AbortController();
    controller.value = ctrl;

    const response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: ctrl.signal,
    });

    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data.detail || `HTTP ${response.status}`);
    }

    return response;
  }

  onBeforeUnmount(() => abort());

  return { consumeStream, fetchStream, abort };
}

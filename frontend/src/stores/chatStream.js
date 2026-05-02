import { parseSseEvent, parseSseFrames } from "@/utils/sse";

export async function consumeSseResponse(response, onEvent) {
  const dataType = response.headers.get("content-type") || "";
  if (!response.ok || !dataType.includes("text/event-stream")) {
    const raw = await response.text();
    throw new Error(raw || "请求失败");
  }
  if (!response.body) {
    throw new Error("响应没有可读取的流。");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const { frames, rest } = parseSseFrames(buffer);
    buffer = rest;
    for (const frame of frames) {
      if (!frame.trim()) continue;
      await onEvent(parseSseEvent(frame));
    }
  }
}

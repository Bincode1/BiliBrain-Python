const DEFAULT_TIMEOUT = 30_000;
const API_BASE_URL = "http://localhost:8000";

export async function api(path, options = {}) {
  const { signal: callerSignal, ...rest } = options;

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), DEFAULT_TIMEOUT);

  // 合并 caller signal 和 timeout signal
  let signal = controller.signal;
  if (callerSignal) {
    if (AbortSignal.any) {
      signal = AbortSignal.any([controller.signal, callerSignal]);
    } else {
      signal = callerSignal;
    }
  }

  const url = `${API_BASE_URL}${path}`;
  const response = await fetch(url, {
    ...rest,
    signal,
    headers: { "Content-Type": "application/json", ...rest.headers },
  });
  clearTimeout(timeout);

  const contentType = response.headers.get("content-type") || "";
  if (!contentType.includes("application/json")) {
    const raw = await response.text();
    throw new Error(`接口没有返回 JSON。响应片段：${raw.slice(0, 120)}`);
  }
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.detail || "请求失败");
  }
  return data;
}

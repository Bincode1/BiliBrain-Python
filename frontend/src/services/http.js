export async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
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

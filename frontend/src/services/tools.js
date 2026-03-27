import { api } from "@/services/http";

export function listTools() {
  return api("/api/tools");
}

export function createToolWorkspace(payload) {
  return api("/api/tools/workspaces", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function listToolWorkspaces(params = {}) {
  const search = new URLSearchParams();
  if (params.featureName) {
    search.set("feature_name", params.featureName);
  }
  if (params.limit) {
    search.set("limit", String(params.limit));
  }
  const suffix = search.toString() ? `?${search.toString()}` : "";
  return api(`/api/tools/workspaces${suffix}`);
}

export function getToolWorkspace(workspaceId) {
  return api(`/api/tools/workspaces/${encodeURIComponent(workspaceId)}`);
}

export function callTool(payload) {
  return api("/api/tools/call", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

import { api } from "@/services/http";

export function listSkills(params = {}) {
  const search = new URLSearchParams();
  if (params.reload) {
    search.set("reload", "true");
  }
  const suffix = search.toString() ? `?${search.toString()}` : "";
  return api(`/api/skills${suffix}`);
}

export function activateSkill(payload) {
  return api("/api/skills/activate", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getSkill(name) {
  return api(`/api/skills/${encodeURIComponent(name)}`);
}

export function deactivateSkill(payload) {
  return api("/api/skills/deactivate", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function createSkill(payload) {
  return api("/api/skills/create", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

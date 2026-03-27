import { api } from "@/services/http";

export function listSkills(params = {}) {
  const search = new URLSearchParams();
  if (params.sessionId) {
    search.set("session_id", params.sessionId);
  }
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

export function getSkillSession(sessionId) {
  return api(`/api/skills/sessions/${encodeURIComponent(sessionId)}`);
}

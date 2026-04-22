import { api } from "@/services/http";

export function getModelSettings() {
  return api("/api/settings/models");
}

export function saveModelSettings(payload) {
  return api("/api/settings/models", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

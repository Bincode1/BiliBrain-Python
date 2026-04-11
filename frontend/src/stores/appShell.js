import { computed, ref } from "vue";
import { defineStore } from "pinia";

import { featureRegistry, featureSections, findFeatureById } from "@/config/features";

const STORAGE_KEY = "app-shell:recent-visits";
const MAX_RECENT = 8;

function loadRecentVisits() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY)) || [];
  } catch {
    return [];
  }
}

function saveRecentVisits(visits) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(visits));
  } catch {
    // ignore quota errors
  }
}

export const useAppShellStore = defineStore("app-shell", () => {
  const features = computed(() => featureRegistry.filter((item) => item.enabled !== false));
  const navSections = computed(() =>
    featureSections.map((section) => ({
      ...section,
      items: section.items.map((itemId) => findFeatureById(itemId)).filter(Boolean),
    }))
  );

  const recentVisits = ref(loadRecentVisits());

  function recordVisit(featureId) {
    if (!featureId) return;
    const list = recentVisits.value.filter((id) => id !== featureId);
    list.unshift(featureId);
    if (list.length > MAX_RECENT) list.length = MAX_RECENT;
    recentVisits.value = list;
    saveRecentVisits(list);
  }

  return {
    features,
    navSections,
    recentVisits,
    recordVisit,
  };
});

import { computed } from "vue";
import { defineStore } from "pinia";

import { featureRegistry, featureSections, findFeatureById } from "@/config/features";

export const useAppShellStore = defineStore("app-shell", () => {
  const features = computed(() => featureRegistry.filter((item) => item.enabled !== false));
  const navSections = computed(() =>
    featureSections.map((section) => ({
      ...section,
      items: section.items.map((itemId) => findFeatureById(itemId)).filter(Boolean),
    }))
  );

  function recordVisit(featureId) {
    return featureId;
  }

  return {
    features,
    navSections,
    recordVisit,
  };
});

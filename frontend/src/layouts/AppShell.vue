<template>
  <div class="workbench-shell" :class="shellToneClass">
    <AppSidebar />

    <div class="shell-main">
      <header v-if="currentFeature" class="shell-header">
        <div class="shell-header-main">
          <div class="shell-header-copy-top">
            <span class="shell-header-kicker">{{ currentFeature.kicker || "BiliBrain" }}</span>
            <span class="shell-header-surface">{{ kindLabel }}</span>
          </div>
          <div class="shell-header-row">
            <h1>{{ currentFeature.name }}</h1>
            <span class="shell-header-badge">{{ currentFeature.badge }}</span>
            <span class="shell-header-status">{{ currentFeature.status }}</span>
          </div>
        </div>
      </header>

      <main class="shell-page">
        <RouterView />
      </main>
    </div>
  </div>
</template>

<script setup>
import { computed, watch } from "vue";
import { RouterView, useRoute } from "vue-router";

import AppSidebar from "@/components/navigation/AppSidebar.vue";
import { findFeatureById } from "@/config/features";
import { useAppShellStore } from "@/stores/appShell";

const route = useRoute();
const store = useAppShellStore();

const currentFeature = computed(() => findFeatureById(route.meta.featureId));
const shellToneClass = computed(() => {
  const featureId = currentFeature.value?.id;
  if (featureId === "chat") return "tone-chat";
  if (featureId === "library") return "tone-library";
  if (featureId === "skills-store") return "tone-skills";
  if (featureId === "tools-store") return "tone-tools";
  return "tone-home";
});
const kindLabel = computed(() => {
  const kind = currentFeature.value?.kind;
  if (kind === "feature") {
    return "功能模块";
  }
  if (kind === "store") {
    return "能力目录";
  }
  return "总览";
});

watch(
  () => route.meta.featureId,
  (featureId) => {
    if (typeof featureId === "string") {
      store.recordVisit(featureId);
    }
  },
  { immediate: true }
);
</script>

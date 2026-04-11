<template>
  <SidebarProvider class="h-svh overflow-hidden">
    <AppSidebar />
    <SidebarInset>
      <div class="h-full overflow-hidden">
        <RouterView />
      </div>
    </SidebarInset>
  </SidebarProvider>
</template>

<script setup>
import { watch } from "vue";
import { RouterView, useRoute } from "vue-router";

import { SidebarProvider, SidebarInset } from "@/components/ui/sidebar";
import AppSidebar from "@/components/navigation/AppSidebar.vue";
import { useAppShellStore } from "@/stores/appShell";

const route = useRoute();
const store = useAppShellStore();

watch(
  () => route.meta.featureId,
  (featureId) => {
    if (typeof featureId === "string") store.recordVisit(featureId);
  },
  { immediate: true }
);
</script>

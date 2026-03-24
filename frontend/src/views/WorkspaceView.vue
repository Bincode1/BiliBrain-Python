<template>
  <div class="app-shell">
    <SidebarPanel />
    <section class="workspace">
      <ChatWorkspace />
    </section>
    <AppDialogModal />
    <DocumentViewerModal />
    <QrLoginModal />
  </div>
</template>

<script setup>
import { onBeforeUnmount, onMounted } from "vue";

import ChatWorkspace from "@/components/chat/ChatWorkspace.vue";
import SidebarPanel from "@/components/layout/SidebarPanel.vue";
import AppDialogModal from "@/components/modals/AppDialogModal.vue";
import DocumentViewerModal from "@/components/modals/DocumentViewerModal.vue";
import QrLoginModal from "@/components/modals/QrLoginModal.vue";
import { useWorkspaceStore } from "@/stores/workspace";

const store = useWorkspaceStore();

onMounted(() => {
  store.initialize();
});

onBeforeUnmount(() => {
  store.cleanup();
});
</script>

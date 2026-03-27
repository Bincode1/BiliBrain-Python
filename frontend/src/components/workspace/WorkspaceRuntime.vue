<template>
  <slot />
  <AppDialogModal />
  <DocumentViewerModal />
  <FolderSearchModal />
  <QrLoginModal />
</template>

<script setup>
import { onBeforeUnmount, onMounted } from "vue";

import AppDialogModal from "@/components/modals/AppDialogModal.vue";
import DocumentViewerModal from "@/components/modals/DocumentViewerModal.vue";
import FolderSearchModal from "@/components/modals/FolderSearchModal.vue";
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

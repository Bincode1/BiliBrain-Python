<template>
  <WorkspaceRuntime>
    <section class="library-feature flex h-full overflow-hidden">
      <SidebarPanel />
      <section class="flex flex-1 flex-col overflow-hidden p-3">
        <CollectionWorkspacePanel />
      </section>
    </section>
  </WorkspaceRuntime>
</template>

<script setup>
import SidebarPanel from "@/components/layout/SidebarPanel.vue";
import CollectionWorkspacePanel from "@/components/workspace/CollectionWorkspacePanel.vue";
import WorkspaceRuntime from "@/components/workspace/WorkspaceRuntime.vue";
</script>

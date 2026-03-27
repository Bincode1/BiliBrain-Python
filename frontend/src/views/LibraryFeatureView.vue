<template>
  <WorkspaceRuntime>
    <section class="library-feature collection-feature-page">
      <div class="library-shell">
        <SidebarPanel />
        <section class="library-workspace collection-workspace">
          <CollectionWorkspacePanel />
        </section>
      </div>
    </section>
  </WorkspaceRuntime>
</template>

<script setup>
import SidebarPanel from "@/components/layout/SidebarPanel.vue";
import CollectionWorkspacePanel from "@/components/workspace/CollectionWorkspacePanel.vue";
import WorkspaceRuntime from "@/components/workspace/WorkspaceRuntime.vue";
</script>

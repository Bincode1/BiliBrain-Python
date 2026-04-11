<template>
  <WorkspaceRuntime>
    <section class="chat-feature-page h-full">
      <ChatWorkspace folder-only />
    </section>
  </WorkspaceRuntime>
</template>

<script setup>
import ChatWorkspace from "@/components/chat/ChatWorkspace.vue";
import WorkspaceRuntime from "@/components/workspace/WorkspaceRuntime.vue";
</script>

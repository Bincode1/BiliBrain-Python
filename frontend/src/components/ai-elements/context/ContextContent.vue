<script setup lang="ts">
import { HoverCardContent } from "@/components/ui/hover-card"
</script>

<template>
  <HoverCardContent class="w-72 p-0" align="end" side="top" :side-offset="8">
    <div class="rounded-xl border bg-popover shadow-md">
      <slot />
    </div>
  </HoverCardContent>
</template>

<script setup lang="ts">
import { HoverCardTrigger } from "@/components/ui/hover-card"
import { useContextState } from "./context"

const { percent } = useContextState()

const circumference = 2 * Math.PI * 7
</script>

<template>
  <HoverCardTrigger as-child>
    <button
      type="button"
      class="inline-flex items-center gap-2 rounded-xl bg-muted/55 px-3 py-2 text-[13px] leading-5 text-foreground/80 hover:bg-muted/70"
    >
      <span>{{ percent.toFixed(1) }}%</span>
      <span class="relative inline-flex h-4 w-4 items-center justify-center">
        <svg class="h-4 w-4 -rotate-90" viewBox="0 0 20 20" aria-hidden="true">
          <circle cx="10" cy="10" r="7" fill="none" stroke="currentColor" stroke-opacity="0.18" stroke-width="1.8" />
          <circle
            cx="10"
            cy="10"
            r="7"
            fill="none"
            stroke="currentColor"
            stroke-width="1.8"
            stroke-linecap="round"
            :stroke-dasharray="`${circumference} ${circumference}`"
            :stroke-dashoffset="circumference * (1 - percent / 100)"
          />
        </svg>
      </span>
    </button>
  </HoverCardTrigger>
</template>

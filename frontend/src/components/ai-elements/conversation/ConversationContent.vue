<script setup lang="ts">
import type { HTMLAttributes } from 'vue'
import { cn } from '@/lib/utils'
import { computed } from 'vue'

interface Props {
  class?: HTMLAttributes['class']
}

const props = defineProps<Props>()

const classes = computed(() => cn(
  'flex flex-col gap-4 p-3',
  props.class,
))
</script>

<template>
  <div :class="classes">
    <slot />
  </div>
</template>

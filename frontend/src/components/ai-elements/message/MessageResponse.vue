<script setup lang="ts">
import type { HTMLAttributes } from 'vue'
import { cn } from '@/lib/utils'
import { computed, nextTick, onMounted, ref, useSlots, watch } from 'vue'
import { Markdown } from 'vue-stream-markdown'
import 'vue-stream-markdown/index.css'

interface Props {
  content?: string
  class?: HTMLAttributes['class']
}

const props = defineProps<Props>()
const rootRef = ref<HTMLElement | null>(null)

const slots = useSlots()
const slotContent = computed<string | undefined>(() => {
  const nodes = slots.default?.()
  if (!Array.isArray(nodes)) {
    return undefined
  }
  let text = ''
  for (const node of nodes) {
    if (typeof node.children === 'string')
      text += node.children
  }
  return text || undefined
})

const md = computed(() => (slotContent.value ?? props.content ?? '') as string)

function decorateInlineCitations() {
  const root = rootRef.value
  if (!root)
    return
  const links = root.querySelectorAll('a')
  links.forEach((link) => {
    const text = (link.textContent || '').trim()
    if (/^资料\s+\d+$/.test(text)) {
      link.classList.add('inline-citation')
      link.setAttribute('target', '_blank')
      link.setAttribute('rel', 'noreferrer')
    }
  })
}

onMounted(() => {
  nextTick(decorateInlineCitations)
})

watch(md, async () => {
  await nextTick()
  decorateInlineCitations()
})
</script>

<template>
  <div ref="rootRef">
    <Markdown
      :content="md"
      :class="
        cn(
          'size-full [&>*:first-child]:mt-0! [&>*:last-child]:mb-0!',
          props.class,
        )
      "
      v-bind="$attrs"
    />
  </div>
</template>

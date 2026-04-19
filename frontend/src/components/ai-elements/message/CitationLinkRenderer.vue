<script setup lang="ts">
import { computed } from 'vue'
import {
  NODE_RENDERERS,
  NodeList,
  useContext,
  useSanitizers,
  type LinkNodeRendererProps,
} from 'vue-stream-markdown'

const props = defineProps<LinkNodeRendererProps>()

const { hardenOptions } = useContext()
const defaultLinkRenderer = NODE_RENDERERS.link

function flattenNodeText(nodes: unknown[]): string {
  return nodes
    .map((node) => {
      if (!node || typeof node !== 'object') {
        return ''
      }
      if (typeof (node as { value?: unknown }).value === 'string') {
        return (node as { value: string }).value
      }
      if (Array.isArray((node as { children?: unknown[] }).children)) {
        return flattenNodeText((node as { children: unknown[] }).children)
      }
      return ''
    })
    .join('')
}

const linkLabel = computed(() => flattenNodeText(props.node.children ?? []).trim())
const isLoading = computed(() => (
  props.node.loading || props.markdownParser.hasLoadingNode(props.node.children)
))

const { transformedUrl, isHardenUrl } = useSanitizers({
  url: computed(() => props.node.url),
  hardenOptions,
  loading: isLoading,
})

const isCitationLink = computed(() => /^资料\s+\d+$/.test(linkLabel.value))
const useCitationPill = computed(() => (
  isCitationLink.value && !!transformedUrl.value && !isHardenUrl.value
))
</script>

<template>
  <span
    v-if="useCitationPill"
    data-stream-markdown="link-container"
    class="inline"
  >
    <a
      data-stream-markdown="link"
      :href="transformedUrl || undefined"
      class="inline-citation"
      rel="noreferrer"
      target="_blank"
    >
      <NodeList
        :markdown-parser="props.markdownParser"
        :node-renderers="props.nodeRenderers"
        :nodes="props.node.children"
        :parent-node="props.node"
        :deep="props.deep + 1"
      />
    </a>
  </span>
  <component
    :is="defaultLinkRenderer"
    v-else
    v-bind="props"
  />
</template>

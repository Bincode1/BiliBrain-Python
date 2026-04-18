<template>
  <article
    class="group w-full"
    :class="message.role === 'user' ? 'is-user flex flex-col items-end' : 'is-assistant'"
  >
    <!-- User badge -->
    <div v-if="message.role === 'user'" class="mb-1.5">
      <div class="inline-flex items-center rounded-md px-2 py-0.5 text-[11px] font-bold bg-secondary text-muted-foreground">
        你
      </div>
    </div>

    <!-- Assistant badges -->
    <div v-else class="flex items-center gap-2 mb-1.5">
      <div class="inline-flex items-center rounded-md px-2 py-0.5 text-[11px] font-bold bg-primary/10 text-primary">
        BiliBrain
      </div>
      <span
        v-if="message.route_mode"
        class="inline-flex items-center rounded-md bg-secondary px-2 py-0.5 text-[10px] font-medium text-muted-foreground"
      >
        {{ messageRouteLabel(message) }}
      </span>
      <span
        v-if="message.answer_mode"
        class="inline-flex items-center rounded-md px-2 py-0.5 text-[10px] font-medium"
        :class="answerModeClass"
      >
        {{ messageModeLabel(message) }}
      </span>
    </div>

    <!-- Reasoning (thinking process) -->
    <Reasoning
      v-if="message.role === 'assistant' && message.reasoning_text"
      :is-streaming="!!message._streaming"
      class="mb-2"
    >
      <ReasoningTrigger />
      <ReasoningContent :content="message.reasoning_text" />
    </Reasoning>

    <!-- Agent panel -->
    <ChatAgentPanel
      v-if="message.role === 'assistant' && hasAgentContent"
      :message="message"
    />

    <!-- Message body -->
    <MessageContent v-if="message.role === 'user'">
      <div class="prose prose-sm max-w-none leading-relaxed" v-html="renderedBody" />
    </MessageContent>
    <div
      v-else
      class="prose prose-sm max-w-none leading-relaxed p-2 text-foreground"
      v-html="renderedBody"
    />

    <!-- Sources -->
    <ChatSourcePanel
      :sources="message.sources"
      :expanded="message.sourcesExpanded"
      :source-label="sourceLabel"
      @toggle="$emit('toggleSources', message)"
    />
  </article>
</template>

<script setup>
import { computed } from "vue";
import {
  messageModeLabel,
  messageRouteLabel,
  messageSourceLabel,
  renderMarkdown,
} from "@/utils/chat";
import ChatAgentPanel from "./ChatAgentPanel.vue";
import ChatSourcePanel from "./ChatSourcePanel.vue";
import { Reasoning, ReasoningTrigger, ReasoningContent } from "@/components/ai-elements/reasoning";
import { MessageContent } from "@/components/ai-elements/message";

const props = defineProps({
  message: { type: Object, required: true },
});

defineEmits(["toggleSources"]);

const hasAgentContent = computed(() =>
  !!(
    props.message.agent_events?.length ||
    props.message.active_skills?.length ||
    props.message.loaded_skills?.length ||
    props.message.skill_events?.length ||
    props.message.tool_events?.length
  )
);

const sourceLabel = computed(() => messageSourceLabel(props.message));

const answerModeClass = computed(() => {
  const mode = props.message.answer_mode;
  if (mode === "summary") return "bg-primary/10 text-primary";
  if (mode === "chunk") return "bg-emerald-50 text-emerald-700";
  return "bg-secondary text-muted-foreground";
});

const renderedBody = computed(() => {
  const text = props.message.text || "";
  const sources = props.message.sources || [];
  try {
    const html = renderMarkdown(text, sources);
    return props.message._streaming ? html + '<span class="streaming-cursor"></span>' : html;
  } catch {
    const fallback = text.replace(/</g, "&lt;").replace(/>/g, "&gt;");
    return props.message._streaming ? fallback + '<span class="streaming-cursor"></span>' : fallback;
  }
});
</script>

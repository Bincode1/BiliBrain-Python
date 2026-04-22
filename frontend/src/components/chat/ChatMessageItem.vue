<template>
  <Message :from="message.role" class="w-full max-w-full">
    <article
      class="w-full"
      :class="message.role === 'user' ? 'flex flex-col items-end' : ''"
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
    <MessageContent
      :class="message.role === 'assistant'
        ? 'w-full max-w-none rounded-none bg-transparent px-0 py-0 text-[14px] leading-7'
        : 'max-w-[min(82%,720px)] text-[14px] leading-7'"
    >
      <MessageResponse
        :content="message.role === 'assistant' ? renderedBody : (message.text || '')"
        :class="message.role === 'assistant'
          ? 'w-full max-w-none rounded-none bg-transparent px-0 py-0 text-[14px] leading-7 [&_p]:my-0'
          : '[&_p]:my-0'"
      />
      <span v-if="message._streaming" class="inline-block h-4 w-2 animate-pulse rounded-sm bg-primary/65 align-middle" />
    </MessageContent>

    <!-- Sources -->
    <ChatSourcePanel
      :sources="message.sources"
      :expanded="message.sourcesExpanded"
      :source-label="sourceLabel"
      @toggle="$emit('toggleSources', message)"
    />
    </article>
  </Message>
</template>

<script setup>
import { computed } from "vue";
import { useChatStore } from "@/stores/chat";
import {
  messageModeLabel,
  messageRouteLabel,
  messageSourceLabel,
  renderMessageMarkdown,
} from "@/utils/chat";
import ChatAgentPanel from "./ChatAgentPanel.vue";
import ChatSourcePanel from "./ChatSourcePanel.vue";
import { Reasoning, ReasoningTrigger, ReasoningContent } from "@/components/ai-elements/reasoning";
import { Message, MessageContent, MessageResponse } from "@/components/ai-elements/message";

const props = defineProps({
  message: { type: Object, required: true },
});

defineEmits(["toggleSources"]);

const store = useChatStore();

const hasAgentContent = computed(() =>
  !!(
    store.hasTaskActivity(props.message.task_id) ||
    props.message.agent_events?.length ||
    props.message.active_skills?.length ||
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
  return renderMessageMarkdown(props.message.text || "", props.message.sources || []);
});
</script>

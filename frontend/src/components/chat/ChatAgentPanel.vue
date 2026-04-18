<template>
  <div v-if="hasEvents" class="not-prose w-full mb-4">
    <Collapsible v-model:open="isOpen" class="group rounded-md border">
      <!-- Header — always visible -->
      <CollapsibleTrigger class="flex w-full items-center justify-between gap-3 px-3 py-2 cursor-pointer select-none hover:bg-muted/50 transition-colors">
        <div class="flex items-center gap-2">
          <component :is="statusIcon(overallState)" :class="statusIconClass(overallState)" />
          <span class="font-medium text-sm">
            {{ headerLabel }}
          </span>
          <Badge v-if="failedCount > 0" class="gap-1 rounded-full text-xs" variant="destructive">
            {{ failedCount }} 失败
          </Badge>
        </div>
        <ChevronDownIcon class="size-4 text-muted-foreground transition-transform duration-200 group-data-[state=open]:rotate-180" />
      </CollapsibleTrigger>

      <!-- Scrollable body -->
      <CollapsibleContent class="overflow-hidden data-[state=closed]:animate-collapsible-up data-[state=open]:animate-collapsible-down">
        <div class="max-h-80 overflow-y-auto overscroll-contain divide-y">
          <div
            v-for="step in allSteps"
            :key="step.id"
            class="px-3 py-2.5"
          >
            <div class="flex items-center gap-2 mb-1.5">
              <component :is="step.icon" class="size-3.5 text-muted-foreground" />
              <span class="font-medium text-sm">{{ step.label }}</span>
              <Badge class="gap-1 rounded-full text-xs" variant="secondary">
                <component :is="statusIcon(step.state)" :class="statusIconClass(step.state)" />
                <span>{{ statusLabel(step.state) }}</span>
              </Badge>
            </div>
            <div v-if="step.input" class="ml-5.5 mb-1">
              <span class="text-xs text-muted-foreground">{{ formatInput(step.input) }}</span>
            </div>
            <div v-if="step.output" class="ml-5.5">
              <span class="text-xs text-muted-foreground truncate block max-w-full">{{ truncateOutput(step.output) }}</span>
            </div>
            <div v-if="step.errorText" class="ml-5.5 text-xs text-destructive">{{ step.errorText }}</div>
          </div>
        </div>
      </CollapsibleContent>
    </Collapsible>
  </div>
</template>

<script setup>
import { computed, ref, watch } from "vue";
import {
  Search,
  FileText,
  Zap,
  List,
  FileSearch,
  FilePenLine,
  FolderPlus,
  FolderOpen,
  Terminal,
  Globe,
  Monitor,
  Wrench,
  ChevronDownIcon,
  CheckCircleIcon,
  ClockIcon,
  XCircleIcon,
  CircleIcon,
} from "lucide-vue-next";
import { Badge } from "@/components/ui/badge";
import { Collapsible, CollapsibleTrigger, CollapsibleContent } from "@/components/ui/collapsible";

const ICON_MAP = {
  search_knowledge_base: Search,
  search_video_summaries: FileText,
  activate_skill: Zap,
  list_active_skills: List,
  read_file: FileSearch,
  write_file: FilePenLine,
  append_file: FilePenLine,
  make_dir: FolderPlus,
  list_dir: FolderOpen,
  run_command: Terminal,
  web_search: Globe,
  browser_read_page: Monitor,
  skill: Zap,
};

const TOOL_LABEL_MAP = {
  search_knowledge_base: "搜索知识库",
  search_video_summaries: "搜索视频摘要",
  activate_skill: "激活技能",
  list_active_skills: "列出已激活技能",
  read_file: "读取文件",
  write_file: "写入文件",
  append_file: "追加文件",
  make_dir: "创建目录",
  list_dir: "列出目录",
  run_command: "执行命令",
  web_search: "网络搜索",
  browser_read_page: "浏览网页",
  skill: "读取技能",
};

const STATUS_ICONS = {
  running: ClockIcon,
  completed: CheckCircleIcon,
  error: XCircleIcon,
  pending: CircleIcon,
};

const STATUS_ICON_CLASSES = {
  running: "size-4 animate-pulse",
  completed: "size-4 text-green-600",
  error: "size-4 text-red-600",
  pending: "size-4",
};

const STATUS_LABELS = {
  running: "运行中",
  completed: "已完成",
  error: "失败",
  pending: "等待中",
};

const props = defineProps({
  message: { type: Object, required: true },
});

const hasEvents = computed(
  () =>
    (props.message.skill_events?.length || 0) +
      (props.message.tool_events?.length || 0) +
      (props.message.loaded_skills?.length || 0) >
    0,
);

const allSteps = computed(() => {
  const result = [];
  const skillEvents = props.message.skill_events || [];
  const toolEvents = props.message.tool_events || [];
  const loadedSkills = props.message.loaded_skills || [];

  // Skill events
  for (const evt of skillEvents) {
    result.push({
      id: evt._id || `skill-${result.length}`,
      label: `${evt.name || "skill"} · ${evt.phase || "start"}`,
      icon: ICON_MAP.skill || Zap,
      state:
        evt.phase === "loaded" ? "completed"
        : evt.phase === "blocked" || evt.phase === "error" ? "error"
        : evt.phase === "approval_required" ? "pending"
        : "running",
      input: evt.message ? { message: evt.message } : null,
      output: evt.phase === "loaded" ? { status: "loaded", skill_root: evt.skill_root || "" } : null,
      errorText: evt.error || null,
    });
  }

  for (const item of loadedSkills) {
    result.push({
      id: `loaded-skill-${item.name}-${result.length}`,
      label: `已加载技能: ${item.name || ""}`,
      icon: ICON_MAP.skill || Zap,
      state: "completed",
      input: {
        actor: item.actor || "agent",
        skill_root: item.skill_root || "",
      },
      output: null,
      errorText: null,
    });
  }

  // Tool events — pair start/finish by key
  const toolStarts = new Map();
  for (const evt of toolEvents) {
    const key = `${evt.name}-${evt.workspace_id || ""}`;
    if (evt.phase === "start") {
      toolStarts.set(key, result.length);
      result.push({
        id: evt._id || `tool-${result.length}`,
        label: TOOL_LABEL_MAP[evt.name] || evt.name || "工具调用",
        icon: ICON_MAP[evt.name] || Wrench,
        state: "running",
        input: evt.summary || {},
        output: null,
        errorText: null,
      });
    } else if (evt.phase === "finish") {
      const idx = toolStarts.get(key);
      if (idx !== undefined) {
        result[idx] = {
          ...result[idx],
          state: evt.ok ? "completed" : "error",
          output: evt.result !== undefined ? evt.result : null,
          errorText: !evt.ok && evt.error ? evt.error : null,
        };
        toolStarts.delete(key);
      }
    }
  }

  // Live agent status while streaming
  if (props.message.agent_status && props.message._streaming) {
    result.push({
      id: "status-thinking",
      label: props.message.agent_status,
      icon: Search,
      state: "running",
      input: null,
      output: null,
      errorText: null,
    });
  }

  return result;
});

// Overall state: running if any step is running, else completed (or error if any error)
const overallState = computed(() => {
  const steps = allSteps.value;
  if (steps.some(s => s.state === "running")) return "running";
  if (steps.some(s => s.state === "error")) return "error";
  return "completed";
});

const failedCount = computed(() => allSteps.value.filter(s => s.state === "error").length);

const headerLabel = computed(() => {
  const total = allSteps.value.length;
  const done = allSteps.value.filter(s => s.state === "completed").length;
  if (overallState.value === "running") return `${total} 个步骤执行中…`;
  return `${done}/${total} 个步骤已完成`;
});

// Auto-collapse when answer starts arriving and streaming ends
const isOpen = ref(true);

watch(
  () => props.message._streaming,
  (streaming, was) => {
    // Collapse once streaming ends AND there is actual answer text
    if (was && !streaming && props.message.text && props.message.text !== "正在思考...") {
      isOpen.value = false;
    }
  },
);

function statusIcon(state) {
  return STATUS_ICONS[state] || CircleIcon;
}
function statusIconClass(state) {
  return STATUS_ICON_CLASSES[state] || "size-4";
}
function statusLabel(state) {
  return STATUS_LABELS[state] || state;
}
function formatInput(input) {
  if (!input || typeof input !== "object") return "";
  const parts = Object.entries(input).map(([k, v]) => `${k}: ${v}`);
  return parts.join(" · ");
}
function truncateOutput(output) {
  if (!output) return "";
  if (typeof output === "string") return output.length > 120 ? output.slice(0, 120) + "…" : output;
  const s = JSON.stringify(output);
  return s.length > 120 ? s.slice(0, 120) + "…" : s;
}
</script>

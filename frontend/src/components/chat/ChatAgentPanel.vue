<template>
  <div v-if="hasEvents" class="not-prose mb-4 w-full">
    <Collapsible v-model:open="isOpen" class="group rounded-md border">
      <CollapsibleTrigger class="flex w-full cursor-pointer select-none items-center justify-between gap-3 px-3 py-2 transition-colors hover:bg-muted/50">
        <div class="flex items-center gap-2">
          <component :is="statusIcon(overallState)" :class="statusIconClass(overallState)" />
          <span class="text-sm font-medium">{{ headerLabel }}</span>
          <Badge v-if="failedCount > 0" class="gap-1 rounded-full text-xs" variant="destructive">
            {{ failedCount }} 失败
          </Badge>
        </div>
        <ChevronDownIcon class="size-4 text-muted-foreground transition-transform duration-200 group-data-[state=open]:rotate-180" />
      </CollapsibleTrigger>

      <CollapsibleContent class="overflow-hidden data-[state=closed]:animate-collapsible-up data-[state=open]:animate-collapsible-down">
        <div class="space-y-3 p-3">
          <div v-if="taskSummary" class="rounded-md border bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
            <div class="flex flex-wrap items-center gap-2">
              <span class="font-medium text-foreground">任务阶段</span>
              <Badge variant="secondary" class="rounded-full text-xs">{{ taskSummary.phaseLabel }}</Badge>
              <span v-if="taskSummary.retryCount > 0">重试 {{ taskSummary.retryCount }} 次</span>
            </div>
            <p v-if="taskSummary.errorText" class="mt-2 text-destructive">{{ taskSummary.errorText }}</p>
          </div>

          <Tool
            v-for="item in renderedActivities"
            :key="item.tool_use_id"
            :default-open="item.state !== 'output-available'"
          >
            <ToolHeader
              type="dynamic-tool"
              :tool-name="item.tool_name"
              :title="item.title"
              :state="item.state"
            />
            <ToolContent>
              <ToolInput :input="item.input" />
              <ToolOutput :output="item.output" :error-text="item.errorText" />
            </ToolContent>
          </Tool>

          <div
            v-for="item in auxiliaryEvents"
            :key="item.id"
            class="rounded-md border bg-background px-3 py-2 text-xs"
          >
            <div class="mb-1 flex items-center gap-2">
              <component :is="item.icon" class="size-3.5 text-muted-foreground" />
              <span class="font-medium text-foreground">{{ item.label }}</span>
              <Badge variant="secondary" class="rounded-full text-xs">{{ statusLabel(item.state) }}</Badge>
            </div>
            <p v-if="item.body" class="text-muted-foreground">{{ item.body }}</p>
          </div>
        </div>
      </CollapsibleContent>
    </Collapsible>
  </div>
</template>

<script setup>
import { computed, ref, watch } from "vue";
import {
  ChevronDownIcon,
  CheckCircleIcon,
  CircleIcon,
  ClockIcon,
  Terminal,
  XCircleIcon,
} from "lucide-vue-next";

import { Badge } from "@/components/ui/badge";
import { Collapsible, CollapsibleTrigger, CollapsibleContent } from "@/components/ui/collapsible";
import { Tool, ToolContent, ToolHeader, ToolInput, ToolOutput } from "@/components/ai-elements/tool";
import { useChatStore } from "@/stores/chat";

const TOOL_LABEL_MAP = {
  search_knowledge_base: "搜索知识库",
  search_video_summaries: "搜索视频摘要",
  read_file: "读取文件",
  write_file: "写入文件",
  append_file: "追加文件",
  make_dir: "创建目录",
  list_dir: "列出目录",
  run_command: "执行命令",
  web_search: "网络搜索",
  browser_read_page: "浏览网页",
  obsidian_write_note: "写入 Obsidian 笔记",
  obsidian_read_note: "读取 Obsidian 笔记",
  skill: "读取技能",
};

const PHASE_LABEL_MAP = {
  preparing: "准备中",
  running: "执行中",
  waiting_approval: "等待审批",
  completed: "已完成",
  rejected: "已拒绝",
  failed: "失败",
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

const store = useChatStore();

const taskBundle = computed(() => store.getTaskBundle(props.message.task_id));
const task = computed(() => taskBundle.value.task);
const taskToolUses = computed(() => taskBundle.value.toolUses || []);
const taskApprovals = computed(() => taskBundle.value.approvals || []);
const taskEvents = computed(() => taskBundle.value.taskEvents || []);

const hasEvents = computed(() =>
  !!(renderedActivities.value.length || auxiliaryEvents.value.length)
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

function latestApprovalFor(toolUseId) {
  return [...taskApprovals.value]
    .filter((item) => String(item.tool_use_id || "") === String(toolUseId || ""))
    .sort((a, b) => String(b.updated_at || "").localeCompare(String(a.updated_at || "")))[0] || null;
}

function mapToolState(toolUse) {
  const latestApproval = latestApprovalFor(toolUse.tool_use_id);
  if (latestApproval?.status === "rejected") return "output-denied";
  if (toolUse.status === "failed") return "output-error";
  if (toolUse.status === "completed") return "output-available";
  if (
    latestApproval?.status === "pending"
    || (task.value?.status === "requires_action" && task.value?.pending_tool_use_id === toolUse.tool_use_id)
  ) {
    return "approval-requested";
  }
  if (latestApproval?.status === "approved") return "approval-responded";
  return "input-available";
}

function toolTimestamp(toolUse) {
  return String(toolUse.started_at || toolUse.updated_at || toolUse.finished_at || "");
}

function hasObjectKeys(value) {
  return !!value && typeof value === "object" && !Array.isArray(value) && Object.keys(value).length > 0;
}

function toolInputValue(toolUse) {
  if (hasObjectKeys(toolUse.raw_input)) return toolUse.raw_input;
  if (hasObjectKeys(toolUse.input_summary)) return toolUse.input_summary;
  return toolUse.raw_input ?? toolUse.input_summary ?? {};
}

function toolErrorText(toolUse) {
  const error = toolUse.error;
  if (typeof error === "string") return error;
  if (!error || typeof error !== "object") return "";
  return error.message || error.detail || JSON.stringify(error);
}

function toolOutputValue(toolUse) {
  if (toolUse.raw_output !== undefined) return toolUse.raw_output;
  return null;
}

const renderedTools = computed(() =>
  [...taskToolUses.value]
    .sort((a, b) => toolTimestamp(a).localeCompare(toolTimestamp(b)))
    .map((toolUse) => ({
      ...toolUse,
      title: TOOL_LABEL_MAP[toolUse.tool_name] || toolUse.tool_name || "工具调用",
      state: mapToolState(toolUse),
      input: toolInputValue(toolUse),
      output: toolOutputValue(toolUse),
      errorText: toolErrorText(toolUse),
      sortTimestamp: toolTimestamp(toolUse),
      sortOrder: 0,
    }))
);

const renderedActivities = computed(() =>
  [...renderedTools.value]
    .sort((a, b) => {
      const timeCompare = String(a.sortTimestamp || "").localeCompare(String(b.sortTimestamp || ""));
      if (timeCompare !== 0) return timeCompare;
      return Number(a.sortOrder || 0) - Number(b.sortOrder || 0);
    })
);

const auxiliaryEvents = computed(() => {
  const items = [];

  const commandFailures = taskEvents.value.filter((item) => item.event_type === "command_failed");
  for (const event of commandFailures) {
    const payload = event.payload || {};
    items.push({
      id: event.event_id || `cmd-${payload.command || ""}`,
      label: `命令失败 (第 ${payload.retry_count || 1} 次)`,
      body: payload.stderr || payload.command || "",
      icon: Terminal,
      state: "error",
    });
  }

  return items;
});

const taskSummary = computed(() => {
  if (!task.value) return null;
  return {
    phaseLabel: PHASE_LABEL_MAP[task.value.phase] || task.value.phase || "unknown",
    retryCount: task.value.retry_count || 0,
    errorText: task.value.failure_reason || "",
  };
});

const overallState = computed(() => {
  if (task.value?.status === "failed" || task.value?.status === "cancelled") return "error";
  const activityStates = renderedActivities.value.map((item) => item.state);
  if (activityStates.some((state) => ["output-error", "output-denied"].includes(state))) return "error";
  if (auxiliaryEvents.value.some((item) => item.state === "error")) return "error";
  if (task.value?.status === "completed") return "completed";
  if (activityStates.some((state) => state === "approval-requested")) return "pending";
  if (auxiliaryEvents.value.some((item) => item.state === "pending")) return "pending";
  if (task.value?.status === "requires_action") return "pending";
  if (activityStates.some((state) => ["input-available", "input-streaming", "approval-responded"].includes(state))) return "running";
  if (auxiliaryEvents.value.some((item) => item.state === "running")) return "running";
  if (task.value?.status === "running" || task.value?.status === "queued") return "running";
  return "completed";
});

const completedActivityCount = computed(() =>
  renderedActivities.value.filter((item) => item.state === "output-available").length
);

const failedActivityCount = computed(() =>
  renderedActivities.value.filter((item) => ["output-error", "output-denied"].includes(item.state)).length
);

const failedCount = computed(() =>
  failedActivityCount.value
  + auxiliaryEvents.value.filter((item) => item.state === "error").length
);

const headerLabel = computed(() => {
  if (!renderedActivities.value.length) return "Agent 活动";
  if (renderedActivities.value.some((item) => item.state === "approval-requested")) {
    return `等待审批 · ${renderedActivities.value.length} 个执行步骤`;
  }
  if (overallState.value === "running") return `${renderedActivities.value.length} 个执行步骤执行中…`;
  if (failedActivityCount.value > 0) {
    return `${failedActivityCount.value} 个步骤失败 · ${completedActivityCount.value}/${renderedActivities.value.length} 已完成`;
  }
  return `${completedActivityCount.value}/${renderedActivities.value.length} 个执行步骤已完成`;
});

const isOpen = ref(true);

watch(
  () => props.message._streaming,
  (streaming, was) => {
    if (was && !streaming && props.message.text && props.message.text !== "正在思考...") {
      isOpen.value = false;
    }
  },
);
</script>

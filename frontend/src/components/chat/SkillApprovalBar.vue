<template>
  <section
    v-if="pendingApproval"
    ref="approvalBarEl"
    class="rounded-xl border border-border bg-card p-4 max-w-3xl w-full"
  >
    <div class="flex flex-col gap-3">
      <div>
        <span class="text-[10px] uppercase tracking-wider text-muted-foreground">审批</span>
        <strong class="ml-2 text-sm">技能代理等待确认</strong>
      </div>

      <div class="flex gap-3 text-xs text-muted-foreground">
        <span>会话编号：<strong class="text-foreground">{{ pendingApproval.sessionId }}</strong></span>
        <span v-if="currentAction?.name">操作：<strong class="text-foreground">{{ currentAction.name }}</strong></span>
      </div>

      <div v-if="currentAction" class="flex flex-col gap-2 rounded-lg bg-secondary p-3">
        <p class="text-sm">{{ approvalDescription }}</p>
        <p v-if="currentAction.policy_reason" class="text-xs" :class="isBlockedAction ? 'text-destructive' : 'text-muted-foreground'">{{ currentAction.policy_reason }}</p>

        <template v-if="isSkillAction">
          <div class="grid gap-2 text-xs text-muted-foreground sm:grid-cols-2">
            <div>
              <label class="text-[10px] uppercase tracking-wider">技能</label>
              <div class="font-mono text-foreground">{{ currentSkillSummary.skill_name || currentAction.args?.name || "-" }}</div>
            </div>
            <div>
              <label class="text-[10px] uppercase tracking-wider">资源数</label>
              <div class="text-foreground">{{ currentSkillSummary.resource_count ?? 0 }}</div>
            </div>
          </div>
          <div v-if="currentSkillSummary.description" class="flex flex-col gap-1">
            <label class="text-[10px] uppercase tracking-wider text-muted-foreground">说明</label>
            <p class="text-xs text-foreground">{{ currentSkillSummary.description }}</p>
          </div>
          <div v-if="skillAllowedToolsText" class="flex flex-col gap-1">
            <label class="text-[10px] uppercase tracking-wider text-muted-foreground">允许工具</label>
            <p class="text-xs font-mono text-foreground">{{ skillAllowedToolsText }}</p>
          </div>
        </template>

        <div v-if="currentAction.name === 'run_command'" class="flex flex-col gap-1">
          <label class="text-[10px] uppercase tracking-wider text-muted-foreground">命令</label>
          <Input v-model.trim="editedCommand" placeholder="python -V" :disabled="isBlockedAction" class="font-mono text-xs" />
        </div>

        <template v-if="usesFilePath">
          <div class="flex flex-col gap-1">
            <label class="text-[10px] uppercase tracking-wider text-muted-foreground">路径</label>
            <Input v-model.trim="editedPath" placeholder="notes.txt" :disabled="isBlockedAction" class="font-mono text-xs" />
          </div>
        </template>

        <div v-if="usesContent" class="flex flex-col gap-1">
          <label class="text-[10px] uppercase tracking-wider text-muted-foreground">内容</label>
          <Textarea v-model="editedContent" placeholder="写入文件中的正文内容..." :disabled="isBlockedAction" rows="3" class="max-h-32 font-mono text-xs" />
        </div>
      </div>

      <div class="flex gap-2">
        <template v-if="isBlockedAction">
          <Button variant="ghost" @click="reject">关闭</Button>
        </template>
        <template v-else>
          <Button @click="approve">同意执行</Button>
          <Button variant="ghost" @click="editAndContinue">修改后继续</Button>
          <Button variant="ghost" class="text-destructive hover:text-destructive" @click="reject">拒绝</Button>
        </template>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed, nextTick, ref, watch } from "vue";
import { storeToRefs } from "pinia";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";

import { useChatStore } from "@/stores/chat";

const store = useChatStore();
const { skillAgentPendingApproval } = storeToRefs(store);

const approvalBarEl = ref(null);
const editedCommand = ref("");
const editedPath = ref("");
const editedContent = ref("");

const pendingApproval = computed(() => skillAgentPendingApproval.value);
const currentAction = computed(() => {
  const actions = pendingApproval.value?.approvalRequest?.action_requests;
  return Array.isArray(actions) && actions.length ? actions[0] : null;
});
const isSkillAction = computed(() => currentAction.value?.name === "skill");
const currentSkillSummary = computed(() => currentAction.value?.summary || {});
const isBlockedAction = computed(() => Boolean(currentAction.value?.policy_blocked));
const usesFilePath = computed(() => ["write_file", "append_file", "make_dir"].includes(currentAction.value?.name || ""));
const usesContent = computed(() => ["write_file", "append_file"].includes(currentAction.value?.name || ""));
const skillAllowedToolsText = computed(() => {
  const tools = currentSkillSummary.value?.allowed_tools;
  return Array.isArray(tools) && tools.length ? tools.join(", ") : "";
});
const approvalDescription = computed(() => {
  if (!currentAction.value) return "这个操作需要你确认后才能继续。";
  if (isSkillAction.value) return `技能 ${currentSkillSummary.value?.skill_name || currentAction.value?.args?.name || ""} 需要你确认后才能加载完整说明。`;
  if (isBlockedAction.value) return "这个操作被当前工具策略禁止，不能通过审批放行。";
  return currentAction.value.description || "这个操作需要你确认后才能继续。";
});

watch(currentAction, (value) => {
  editedCommand.value = value?.args?.command || "";
  editedPath.value = value?.args?.path || "";
  editedContent.value = value?.args?.content || "";
}, { immediate: true });

watch(pendingApproval, async (value) => {
  if (!value) return;
  await nextTick();
  approvalBarEl.value?.scrollIntoView({ behavior: "smooth", block: "nearest" });
});

function approve() {
  if (!currentAction.value) return;
  store.resumeSkillAgentApproval({
    type: "approve",
    name: currentAction.value.name,
    args: currentAction.value.args || {},
  });
}
function reject() {
  store.resumeSkillAgentApproval({
    type: "reject",
    message: isBlockedAction.value
      ? `用户关闭了被策略禁止的操作：${currentAction.value?.policy_reason || "策略已阻止该操作"}。`
      : isSkillAction.value
        ? `用户拒绝加载技能 ${currentSkillSummary.value?.skill_name || currentAction.value?.args?.name || ""}。`
        : "用户拒绝了当前操作。",
  });
}
function editAndContinue() {
  if (!currentAction.value) return;
  const nextArgs = { ...(currentAction.value.args || {}) };
  if (currentAction.value.name === "run_command") nextArgs.command = editedCommand.value || nextArgs.command || "";
  if (usesFilePath.value) nextArgs.path = editedPath.value || nextArgs.path || "";
  if (usesContent.value) nextArgs.content = editedContent.value ?? nextArgs.content ?? "";
  store.resumeSkillAgentApproval({
    type: "edit",
    name: currentAction.value.name,
    args: nextArgs,
  });
}
</script>

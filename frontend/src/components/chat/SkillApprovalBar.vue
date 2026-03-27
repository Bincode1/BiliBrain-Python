<template>
  <section v-if="pendingApproval" ref="approvalBarEl" class="active-skills-bar approval-bar">
    <div class="active-skills-bar-head">
      <div>
        <span class="tool-panel-kicker">审批</span>
        <strong>技能代理等待确认</strong>
      </div>
    </div>

    <div class="active-skills-meta">
      <span>会话编号：<strong>{{ pendingApproval.sessionId }}</strong></span>
      <span v-if="currentAction?.name">操作：<strong>{{ currentAction.name }}</strong></span>
    </div>

    <div v-if="currentAction" class="approval-card">
      <p class="approval-description">{{ approvalDescription }}</p>
      <p v-if="isBlockedAction" class="approval-policy-error">{{ currentAction.policy_reason }}</p>
      <label v-if="currentAction.name === 'run_command'" class="tool-field">
        <span>命令</span>
        <input v-model.trim="editedCommand" placeholder="python -V" :disabled="isBlockedAction" />
      </label>
      <template v-if="usesFilePath">
        <label class="tool-field">
          <span>路径</span>
          <input v-model.trim="editedPath" placeholder="notes.txt" :disabled="isBlockedAction" />
        </label>
      </template>
      <label v-if="usesContent" class="tool-field">
        <span>内容</span>
        <textarea v-model="editedContent" placeholder="写入文件中的正文内容..." :disabled="isBlockedAction" />
      </label>
    </div>

    <div class="tool-action-row">
      <template v-if="isBlockedAction">
        <button type="button" class="ghost-button" @click="reject">关闭</button>
      </template>
      <template v-else>
        <button type="button" @click="approve">同意执行</button>
        <button type="button" class="ghost-button" @click="editAndContinue">修改后继续</button>
        <button type="button" class="ghost-button" @click="reject">拒绝</button>
      </template>
    </div>
  </section>
</template>

<script setup>
import { computed, nextTick, ref, watch } from "vue";
import { storeToRefs } from "pinia";

import { useWorkspaceStore } from "@/stores/workspace";

const store = useWorkspaceStore();
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
const isBlockedAction = computed(() => Boolean(currentAction.value?.policy_blocked));
const usesFilePath = computed(() => ["write_file", "append_file", "make_dir"].includes(currentAction.value?.name || ""));
const usesContent = computed(() => ["write_file", "append_file"].includes(currentAction.value?.name || ""));
const approvalDescription = computed(() => {
  if (!currentAction.value) {
    return "这个操作需要你确认后才能继续。";
  }
  if (isBlockedAction.value) {
    return "这个操作被当前工具策略禁止，不能通过审批放行。";
  }
  return currentAction.value.description || "这个操作需要你确认后才能继续。";
});

watch(currentAction, (value) => {
  editedCommand.value = value?.args?.command || "";
  editedPath.value = value?.args?.path || "";
  editedContent.value = value?.args?.content || "";
}, { immediate: true });

watch(pendingApproval, async (value) => {
  if (!value) {
    return;
  }
  await nextTick();
  approvalBarEl.value?.scrollIntoView({
    behavior: "smooth",
    block: "nearest",
  });
});

function approve() {
  store.resumeSkillAgentApproval({ type: "approve" });
}

function reject() {
  store.resumeSkillAgentApproval({
    type: "reject",
    message: isBlockedAction.value
      ? `用户关闭了被策略禁止的操作：${currentAction.value?.policy_reason || "策略已阻止该操作"}。`
      : "用户拒绝了当前操作。",
  });
}

function editAndContinue() {
  if (!currentAction.value) {
    return;
  }
  const nextArgs = {
    ...(currentAction.value.args || {}),
  };
  if (currentAction.value.name === "run_command") {
    nextArgs.command = editedCommand.value || nextArgs.command || "";
  }
  if (usesFilePath.value) {
    nextArgs.path = editedPath.value || nextArgs.path || "";
  }
  if (usesContent.value) {
    nextArgs.content = editedContent.value ?? nextArgs.content ?? "";
  }
  store.resumeSkillAgentApproval({
    type: "edit",
    edited_action: {
      name: currentAction.value.name,
      args: nextArgs,
    },
  });
}
</script>

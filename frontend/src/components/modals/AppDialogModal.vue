<template>
  <div v-if="dialogOpen" class="modal-shell" @click.self="handleCancel">
    <div class="modal-card app-dialog-card">
      <div class="panel-head app-dialog-head">
        <h2>{{ dialogTitle }}</h2>
        <p v-if="dialogMessage">{{ dialogMessage }}</p>
      </div>
      <label v-if="dialogMode === 'prompt'" class="app-dialog-field">
        <span class="app-dialog-label">会话名称</span>
        <input
          ref="inputEl"
          v-model="dialogInput"
          class="app-dialog-input"
          type="text"
          :placeholder="dialogPlaceholder"
          maxlength="255"
          @keydown.enter.prevent="handleConfirm"
          @keydown.esc.prevent="handleCancel"
        />
      </label>
      <div class="modal-actions app-dialog-actions">
        <button class="ghost-button" type="button" @click="handleCancel">
          {{ dialogCancelLabel }}
        </button>
        <button
          class="app-dialog-confirm"
          :class="{ danger: dialogTone === 'danger' }"
          type="button"
          @click="handleConfirm"
        >
          {{ dialogConfirmLabel }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { nextTick, ref, watch } from "vue";
import { storeToRefs } from "pinia";

import { useWorkspaceStore } from "@/stores/workspace";

const store = useWorkspaceStore();
const {
  dialogOpen,
  dialogMode,
  dialogTitle,
  dialogMessage,
  dialogInput,
  dialogPlaceholder,
  dialogConfirmLabel,
  dialogCancelLabel,
  dialogTone,
} = storeToRefs(store);
const inputEl = ref(null);

function handleCancel() {
  store.closeDialog(null);
}

function handleConfirm() {
  if (dialogMode.value === "prompt") {
    store.closeDialog(dialogInput.value);
    return;
  }
  store.closeDialog(true);
}

watch(dialogOpen, async (open) => {
  if (!open || dialogMode.value !== "prompt") {
    return;
  }
  await nextTick();
  inputEl.value?.focus?.();
  inputEl.value?.select?.();
});
</script>

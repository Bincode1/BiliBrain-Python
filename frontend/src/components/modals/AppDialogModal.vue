<template>
  <Dialog :open="dialogOpen" @update:open="(v) => !v && handleCancel()">
    <DialogContent class="sm:max-w-md">
      <DialogHeader>
        <DialogTitle>{{ dialogTitle }}</DialogTitle>
        <DialogDescription v-if="dialogMessage">{{ dialogMessage }}</DialogDescription>
      </DialogHeader>

      <div v-if="dialogMode === 'prompt'" class="py-2">
        <Input
          ref="inputEl"
          v-model="dialogInput"
          :placeholder="dialogPlaceholder"
          maxlength="255"
          @keydown.enter.prevent="handleConfirm"
          @keydown.esc.prevent="handleCancel"
        />
      </div>

      <DialogFooter class="gap-2 sm:gap-0">
        <Button variant="ghost" @click="handleCancel">
          {{ dialogCancelLabel }}
        </Button>
        <Button
          :variant="dialogTone === 'danger' ? 'destructive' : 'default'"
          @click="handleConfirm"
        >
          {{ dialogConfirmLabel }}
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>

<script setup>
import { nextTick, ref, watch } from "vue";
import { storeToRefs } from "pinia";

import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

import { useDialogStore } from "@/stores/dialog";

const store = useDialogStore();
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
  if (!open || dialogMode.value !== "prompt") return;
  await nextTick();
  inputEl.value?.$el?.focus?.();
  inputEl.value?.$el?.select?.();
});
</script>

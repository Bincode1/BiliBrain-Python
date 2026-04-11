import { ref } from "vue";
import { defineStore } from "pinia";

export const useDialogStore = defineStore("dialog", () => {
  const dialogOpen = ref(false);
  const dialogMode = ref("confirm");
  const dialogTitle = ref("");
  const dialogMessage = ref("");
  const dialogInput = ref("");
  const dialogPlaceholder = ref("");
  const dialogConfirmLabel = ref("确定");
  const dialogCancelLabel = ref("取消");
  const dialogTone = ref("default");

  let dialogResolver = null;

  function openDialog(options = {}) {
    dialogMode.value = options.mode || "confirm";
    dialogTitle.value = options.title || "";
    dialogMessage.value = options.message || "";
    dialogInput.value = options.initialValue || "";
    dialogPlaceholder.value = options.placeholder || "";
    dialogConfirmLabel.value = options.confirmLabel || "确定";
    dialogCancelLabel.value = options.cancelLabel || "取消";
    dialogTone.value = options.tone || "default";
    dialogOpen.value = true;
    return new Promise((resolve) => {
      dialogResolver = resolve;
    });
  }

  function closeDialog(result = null) {
    dialogOpen.value = false;
    const resolver = dialogResolver;
    dialogResolver = null;
    if (resolver) {
      resolver(result);
    }
  }

  function confirmDialog(options = {}) {
    return openDialog({ ...options, mode: "confirm" });
  }

  function promptDialog(options = {}) {
    return openDialog({ ...options, mode: "prompt" });
  }

  function cleanup() {
    if (dialogResolver) {
      dialogResolver(null);
      dialogResolver = null;
    }
  }

  return {
    dialogOpen,
    dialogMode,
    dialogTitle,
    dialogMessage,
    dialogInput,
    dialogPlaceholder,
    dialogConfirmLabel,
    dialogCancelLabel,
    dialogTone,
    openDialog,
    closeDialog,
    confirmDialog,
    promptDialog,
    cleanup,
  };
});

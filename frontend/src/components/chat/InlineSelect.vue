<template>
  <div ref="rootRef" class="inline-select" :class="{ open, disabled }">
    <button
      class="inline-select-trigger"
      type="button"
      :disabled="disabled"
      :title="title || currentLabel"
      :aria-expanded="open ? 'true' : 'false'"
      @click="toggle"
    >
      <span class="inline-select-label">{{ currentLabel }}</span>
      <span class="inline-select-caret" aria-hidden="true"></span>
    </button>

    <div v-if="open" class="inline-select-menu">
      <button
        v-for="option in normalizedOptions"
        :key="option.value"
        class="inline-select-option"
        :class="{ active: option.value === normalizedValue }"
        type="button"
        :disabled="option.disabled"
        @click="selectOption(option.value)"
      >
        <span>{{ option.label }}</span>
      </button>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from "vue";

const props = defineProps({
  modelValue: {
    type: String,
    default: "",
  },
  options: {
    type: Array,
    default: () => [],
  },
  placeholder: {
    type: String,
    default: "",
  },
  disabled: {
    type: Boolean,
    default: false,
  },
  title: {
    type: String,
    default: "",
  },
});

const emit = defineEmits(["update:modelValue"]);

const rootRef = ref(null);
const open = ref(false);

const normalizedValue = computed(() => String(props.modelValue ?? ""));
const normalizedOptions = computed(() =>
  props.options.map((option) => ({
    value: String(option.value ?? ""),
    label: String(option.label ?? ""),
    disabled: Boolean(option.disabled),
  }))
);

const currentLabel = computed(() => {
  const matched = normalizedOptions.value.find((option) => option.value === normalizedValue.value);
  return matched?.label || props.placeholder || "";
});

function toggle() {
  if (props.disabled) {
    return;
  }
  open.value = !open.value;
}

function selectOption(value) {
  emit("update:modelValue", String(value ?? ""));
  open.value = false;
}

function handleDocumentClick(event) {
  if (!open.value) {
    return;
  }
  const target = event.target;
  if (rootRef.value instanceof HTMLElement && target instanceof Node && rootRef.value.contains(target)) {
    return;
  }
  open.value = false;
}

function handleKeydown(event) {
  if (event.key === "Escape") {
    open.value = false;
  }
}

onMounted(() => {
  document.addEventListener("click", handleDocumentClick);
  document.addEventListener("keydown", handleKeydown);
});

onBeforeUnmount(() => {
  document.removeEventListener("click", handleDocumentClick);
  document.removeEventListener("keydown", handleKeydown);
});
</script>

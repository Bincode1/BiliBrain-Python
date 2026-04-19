<template>
  <Select
    :model-value="normalizedValue"
    :disabled="disabled"
    @update:model-value="emit('update:modelValue', String($event ?? ''))"
  >
    <SelectTrigger :class="triggerClasses">
      <SelectValue :placeholder="placeholder || currentLabel" class="truncate" />
    </SelectTrigger>
    <SelectContent class="min-w-[140px]" position="popper" :side-offset="4">
      <SelectItem
        v-for="option in normalizedOptions"
        :key="option.value"
        :value="option.value"
        :disabled="option.disabled"
        class="text-xs"
      >
        {{ option.label }}
      </SelectItem>
    </SelectContent>
  </Select>
</template>

<script setup>
import { computed } from "vue";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

const props = defineProps({
  modelValue: { type: String, default: "" },
  options: { type: Array, default: () => [] },
  placeholder: { type: String, default: "" },
  disabled: { type: Boolean, default: false },
  title: { type: String, default: "" },
  triggerClass: { type: String, default: "" },
});

const emit = defineEmits(["update:modelValue"]);

const normalizedValue = computed(() => String(props.modelValue ?? ""));
const normalizedOptions = computed(() =>
  props.options.map((o) => ({
    value: String(o.value ?? ""),
    label: String(o.label ?? ""),
    disabled: Boolean(o.disabled),
  }))
);
const currentLabel = computed(() => {
  const match = normalizedOptions.value.find((o) => o.value === normalizedValue.value);
  return match?.label || "";
});
const triggerClasses = computed(() =>
  [
    "h-8 gap-1 rounded-full border border-border/70 bg-secondary px-3 text-[13px] text-foreground shadow-none hover:bg-accent",
    "max-w-full min-w-0 [&>span]:truncate",
    props.triggerClass,
  ].join(" ")
);
</script>

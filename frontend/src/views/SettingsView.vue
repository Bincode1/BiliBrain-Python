<template>
  <div class="flex h-full">
    <aside class="w-44 shrink-0 border-r border-border px-2 py-4">
      <nav class="space-y-1">
        <button
          v-for="tab in tabs"
          :key="tab.id"
          class="w-full rounded-md px-3 py-2 text-left text-sm transition-colors"
          :class="activeTab === tab.id
            ? 'bg-primary/10 text-primary font-medium'
            : 'text-muted-foreground hover:bg-accent'"
          @click="activeTab = tab.id"
        >
          {{ tab.label }}
        </button>
      </nav>
    </aside>

    <main class="flex-1 overflow-y-auto px-8 py-6 max-w-3xl">
      <template v-if="activeTab === 'models'">
        <div class="mb-6">
          <h2 class="text-base font-semibold">模型配置</h2>
          <p class="mt-1 text-xs text-muted-foreground">
            每组配置只需要填写 `model / base_url / api_key`。Base URL 指向本地 Ollama 时自动走 `langchain-ollama`，其他地址按 OpenAI 兼容 API 走 `langchain-openai`。
          </p>
        </div>

        <ApiModelSection
          title="Chat Model"
          description="用于对话、总结、记忆压缩、规划和 agent 工具调用。"
          model-placeholder="qwen3.5:4b 或 deepseek-chat"
          :model="form.chat.model"
          :base-url="form.chat.base_url"
          :api-key="apiKeyValue('chat')"
          :api-key-configured="hasStoredApiKey('chat')"
          :api-key-placeholder="apiKeyPlaceholder('chat')"
          :api-key-hint="apiKeyHint('chat', '本地 Ollama 一般不需要 API Key。')"
          @update:model="form.chat.model = $event"
          @update:base-url="form.chat.base_url = $event"
          @update:api-key="updateApiKey('chat', $event)"
          @clear-api-key="clearApiKey('chat')"
        />

        <ApiModelSection
          title="Embedding Model"
          description="用于视频切片向量化和语义检索。更换 embedding 模型后，通常需要重新入库或重建索引。"
          model-placeholder="bge-m3 或 text-embedding-3-large"
          :model="form.embedding.model"
          :base-url="form.embedding.base_url"
          :api-key="apiKeyValue('embedding')"
          :api-key-configured="hasStoredApiKey('embedding')"
          :api-key-placeholder="apiKeyPlaceholder('embedding')"
          :api-key-hint="apiKeyHint('embedding', '本地 Ollama 一般不需要 API Key。')"
          @update:model="form.embedding.model = $event"
          @update:base-url="form.embedding.base_url = $event"
          @update:api-key="updateApiKey('embedding', $event)"
          @clear-api-key="clearApiKey('embedding')"
        />

        <ApiModelSection
          title="ASR Model"
          description="用于音频转写。这里默认按 OpenAI 兼容接口处理。"
          model-placeholder="qwen3-asr-flash"
          :model="form.asr.model"
          :base-url="form.asr.base_url"
          :api-key="apiKeyValue('asr')"
          :api-key-configured="hasStoredApiKey('asr')"
          :api-key-placeholder="apiKeyPlaceholder('asr')"
          :api-key-hint="apiKeyHint('asr', '')"
          @update:model="form.asr.model = $event"
          @update:base-url="form.asr.base_url = $event"
          @update:api-key="updateApiKey('asr', $event)"
          @clear-api-key="clearApiKey('asr')"
        />

        <div class="mt-8 flex items-center gap-4">
          <button
            class="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
            :disabled="saving"
            @click="handleSave"
          >
            {{ saving ? '保存中...' : '保存配置' }}
          </button>
          <span v-if="saveStatus === 'success'" class="text-xs text-green-500">保存成功，请重启后端服务</span>
          <span v-else-if="saveStatus === 'error'" class="text-xs text-destructive">保存失败，请重试</span>
          <span v-else class="text-xs text-amber-500">保存后需重启后端服务生效</span>
        </div>
      </template>

      <template v-if="activeTab === 'general'">
        <h2 class="text-base font-semibold mb-4">通用设置</h2>
        <p class="text-sm text-muted-foreground">暂无其他设置项。</p>
      </template>
    </main>
  </div>
</template>

<script setup>
import { defineComponent, h, onMounted, ref } from "vue";
import { getModelSettings, saveModelSettings } from "@/services/settings";

const REDACTED = "__REDACTED__";

const ApiModelSection = defineComponent({
  name: "ApiModelSection",
  props: {
    title: { type: String, required: true },
    description: { type: String, default: "" },
    modelPlaceholder: { type: String, default: "" },
    model: { type: String, default: "" },
    baseUrl: { type: String, default: "" },
    apiKey: { type: String, default: "" },
    apiKeyConfigured: { type: Boolean, default: false },
    apiKeyPlaceholder: { type: String, default: "sk-..." },
    apiKeyHint: { type: String, default: "" },
  },
  emits: ["update:model", "update:base-url", "update:api-key", "clear-api-key"],
  setup(props, { emit }) {
    const inputClass = "w-full rounded-md border border-input bg-background px-3 py-1.5 text-sm outline-none focus:ring-1 focus:ring-ring";
    const labelClass = "mb-1 block text-xs text-muted-foreground";
    const field = (label, value, event, attrs = {}) => h("div", [
      h("label", { class: labelClass }, label),
      h("input", {
        ...attrs,
        value,
        class: inputClass,
        onInput: (inputEvent) => emit(event, inputEvent.target.value),
      }),
    ]);
    return () => h("section", { class: "mb-6 rounded-lg border border-border p-4" }, [
      h("div", { class: "mb-4" }, [
        h("h3", { class: "text-sm font-semibold" }, props.title),
        props.description ? h("p", { class: "mt-1 text-xs text-muted-foreground" }, props.description) : null,
      ]),
      h("div", { class: "space-y-3" }, [
        field("模型名称", props.model, "update:model", { placeholder: props.modelPlaceholder }),
        field("Base URL", props.baseUrl, "update:base-url", { placeholder: "http://127.0.0.1:11434 或 https://.../v1" }),
        h("div", [
          h("div", { class: "mb-1 flex items-center justify-between" }, [
            h("label", { class: labelClass }, "API Key"),
            props.apiKeyConfigured
              ? h("button", {
                type: "button",
                class: "text-[11px] text-muted-foreground transition-colors hover:text-foreground",
                onClick: () => emit("clear-api-key"),
              }, "清空")
              : null,
          ]),
          h("input", {
            type: "password",
            value: props.apiKey,
            placeholder: props.apiKeyPlaceholder,
            class: inputClass,
            onInput: (inputEvent) => emit("update:api-key", inputEvent.target.value),
          }),
          props.apiKeyHint ? h("p", { class: "mt-1 text-[11px] text-muted-foreground" }, props.apiKeyHint) : null,
        ]),
      ]),
    ]);
  },
});

const tabs = [
  { id: "models", label: "模型配置" },
  { id: "general", label: "通用设置" },
];
const activeTab = ref("models");
const saving = ref(false);
const saveStatus = ref(null);

const form = ref({
  chat: { model: "", base_url: "", api_key: "" },
  embedding: { model: "", base_url: "", api_key: "" },
  asr: { model: "", base_url: "", api_key: "" },
});

function apiKeyValue(section) {
  return form.value[section].api_key === REDACTED ? "" : form.value[section].api_key;
}

function hasStoredApiKey(section) {
  return form.value[section].api_key === REDACTED || Boolean(form.value[section].api_key);
}

function apiKeyPlaceholder(section) {
  return form.value[section].api_key === REDACTED ? "已配置，直接保存会保持原值" : "sk-...";
}

function apiKeyHint(section, emptyHint) {
  if (form.value[section].api_key === REDACTED) return "当前已配置，未修改时会保持原值。";
  if (!form.value[section].api_key) return emptyHint;
  return "";
}

function updateApiKey(section, value) {
  form.value[section].api_key = value;
}

function clearApiKey(section) {
  form.value[section].api_key = "";
}

function buildSavePayload() {
  return {
    chat: { ...form.value.chat },
    embedding: { ...form.value.embedding },
    asr: { ...form.value.asr },
  };
}

onMounted(async () => {
  const data = await getModelSettings();
  form.value = {
    chat: { ...data.chat },
    embedding: { ...data.embedding },
    asr: { ...data.asr },
  };
});

async function handleSave() {
  saving.value = true;
  saveStatus.value = null;
  try {
    await saveModelSettings(buildSavePayload());
    saveStatus.value = "success";
  } catch {
    saveStatus.value = "error";
  } finally {
    saving.value = false;
    setTimeout(() => { saveStatus.value = null; }, 3000);
  }
}
</script>

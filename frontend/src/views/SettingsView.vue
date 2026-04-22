<template>
  <div class="flex h-full">
    <!-- Left nav -->
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

    <!-- Content -->
    <main class="flex-1 overflow-y-auto px-8 py-6 max-w-2xl">
      <template v-if="activeTab === 'models'">
        <h2 class="text-base font-semibold mb-6">模型配置</h2>

        <!-- LLM -->
        <section class="mb-6">
          <h3 class="text-sm font-medium text-foreground/70 mb-3 uppercase tracking-wide">LLM 模型</h3>
          <div class="space-y-3">
            <div>
              <label class="text-xs text-muted-foreground mb-1 block">模型名称</label>
              <input v-model="form.llm_model" class="input-field" placeholder="qwen-plus" />
            </div>
            <div>
              <label class="text-xs text-muted-foreground mb-1 block">Base URL</label>
              <input v-model="form.dashscope_base_url" class="input-field" />
            </div>
            <div>
              <label class="text-xs text-muted-foreground mb-1 block">API Key</label>
              <input v-model="form.dashscope_api_key" type="password" class="input-field" placeholder="sk-..." />
            </div>
          </div>
        </section>

        <div class="border-t border-border mb-6" />

        <!-- Embedding -->
        <section class="mb-6">
          <h3 class="text-sm font-medium text-foreground/70 mb-3 uppercase tracking-wide">Embedding 模型</h3>
          <div class="space-y-3">
            <div>
              <label class="text-xs text-muted-foreground mb-1 block">模型名称</label>
              <input v-model="form.embedding_model" class="input-field" />
            </div>
            <div>
              <label class="text-xs text-muted-foreground mb-1 block">Ollama Base URL</label>
              <input v-model="form.ollama_base_url" class="input-field" />
            </div>
          </div>
        </section>

        <div class="border-t border-border mb-6" />

        <!-- ASR -->
        <section class="mb-8">
          <h3 class="text-sm font-medium text-foreground/70 mb-3 uppercase tracking-wide">ASR 模型</h3>
          <div class="space-y-3">
            <div>
              <label class="text-xs text-muted-foreground mb-1 block">模型名称</label>
              <input v-model="form.asr_api_model" class="input-field" />
            </div>
            <div>
              <label class="text-xs text-muted-foreground mb-1 block">Base URL</label>
              <input v-model="form.asr_api_base_url" class="input-field" />
            </div>
          </div>
        </section>

        <!-- Save -->
        <div class="flex items-center gap-4">
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
import { ref, onMounted } from "vue";
import { getModelSettings, saveModelSettings } from "@/services/settings";

const tabs = [
  { id: "models", label: "模型配置" },
  { id: "general", label: "通用设置" },
];
const activeTab = ref("models");
const saving = ref(false);
const saveStatus = ref(null); // null | 'success' | 'error'

const form = ref({
  llm_model: "",
  dashscope_api_key: "",
  dashscope_base_url: "",
  embedding_model: "",
  ollama_base_url: "",
  asr_api_model: "",
  asr_api_base_url: "",
});

onMounted(async () => {
  const data = await getModelSettings();
  Object.assign(form.value, data);
});

async function handleSave() {
  saving.value = true;
  saveStatus.value = null;
  try {
    await saveModelSettings(form.value);
    saveStatus.value = "success";
  } catch {
    saveStatus.value = "error";
  } finally {
    saving.value = false;
    setTimeout(() => { saveStatus.value = null; }, 3000);
  }
}
</script>

<style scoped>
.input-field {
  @apply w-full rounded-md border border-input bg-background px-3 py-1.5 text-sm outline-none focus:ring-1 focus:ring-ring;
}
</style>

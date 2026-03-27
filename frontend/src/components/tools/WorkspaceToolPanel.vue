<template>
  <section class="tool-workspace-panel">
    <div class="tool-panel-grid">
      <article class="tool-panel-card">
        <div class="tool-panel-head">
          <div>
            <span class="tool-panel-kicker">工作区</span>
            <h3>工具工作区</h3>
          </div>
          <span class="tool-panel-badge" :class="{ disabled: !toolsEnabled }">
            {{ toolsEnabled ? "已启用" : "未启用" }}
          </span>
        </div>

        <p class="tool-panel-copy">
          在当前工作台里手动创建一个工具工作区，然后调用文件或命令工具验证后端 runtime。
        </p>

        <div class="tool-form-grid">
          <label class="tool-field">
            <span>功能标识</span>
            <input v-model.trim="workspaceForm.featureName" placeholder="tools" />
          </label>
          <label class="tool-field">
            <span>工作区名称</span>
            <input v-model.trim="workspaceForm.title" placeholder="工具沙箱" />
          </label>
        </div>

        <div class="tool-action-row">
          <button :disabled="creatingWorkspace" @click="handleCreateWorkspace">
            {{ creatingWorkspace ? "创建中..." : "创建工作区" }}
          </button>
          <button class="ghost-button" :disabled="refreshingPanel" @click="refreshPanel">
            {{ refreshingPanel ? "刷新中..." : "刷新面板" }}
          </button>
        </div>

        <label class="tool-field">
          <span>当前工作区</span>
          <select v-model="selectedWorkspaceId" :disabled="loadingWorkspaces || !workspaceOptions.length">
            <option v-if="!workspaceOptions.length" value="">暂时还没有工作区</option>
            <option v-for="item in workspaceOptions" :key="item.workspace_id" :value="item.workspace_id">
              {{ item.display_name }}
            </option>
          </select>
        </label>

        <div class="tool-workspace-meta">
          <span v-if="workspace">工作区：<strong>{{ workspace.display_name || workspace.workspace_id }}</strong></span>
          <span v-if="workspace">编号：{{ workspace.workspace_id }}</span>
          <span v-if="workspace?.root_path">根目录：{{ workspace.root_path }}</span>
          <span v-if="errorText" class="tool-error-text">{{ errorText }}</span>
          <span v-if="infoText && !errorText" class="tool-info-text">{{ infoText }}</span>
        </div>
      </article>

      <article class="tool-panel-card">
        <div class="tool-panel-head">
          <div>
            <span class="tool-panel-kicker">执行器</span>
            <h3>运行工具</h3>
          </div>
          <span class="tool-panel-badge subtle">{{ selectedToolMeta?.approval_mode || "auto" }}</span>
        </div>

        <label class="tool-field">
          <span>工具</span>
          <select v-model="selectedToolName">
            <option v-for="item in availableTools" :key="item.name" :value="item.name">
              {{ item.name }}
            </option>
          </select>
        </label>

        <div class="tool-form-grid">
          <label v-if="usesPath" class="tool-field">
            <span>路径</span>
            <input v-model="form.path" :placeholder="pathPlaceholder" />
          </label>
          <label v-if="usesQuery" class="tool-field tool-field-wide">
            <span>搜索词</span>
            <input v-model="form.query" placeholder="东京 5 日 旅行 攻略" />
          </label>
          <label v-if="usesMaxResults" class="tool-field">
            <span>结果数</span>
            <input v-model.number="form.maxResults" type="number" min="1" max="10" />
          </label>
          <label v-if="usesEncoding" class="tool-field">
            <span>编码</span>
            <input v-model="form.encoding" placeholder="utf-8" />
          </label>
          <label v-if="usesCommand" class="tool-field tool-field-wide">
            <span>命令</span>
            <input v-model="form.command" placeholder="python -V" />
          </label>
          <label v-if="usesCwd" class="tool-field">
            <span>运行目录</span>
            <input v-model="form.cwd" placeholder="." />
          </label>
          <label v-if="usesTimeout" class="tool-field">
            <span>超时（秒）</span>
            <input v-model.number="form.timeoutSeconds" type="number" min="1" />
          </label>
        </div>

        <label v-if="usesContent" class="tool-field">
          <span>内容</span>
          <textarea v-model="form.content" placeholder="写入到当前工作区文件中的正文..." />
        </label>

        <div v-if="usesOverwrite" class="tool-toggle-row">
          <label>
            <input v-model="form.overwrite" type="checkbox" />
            覆盖同名文件
          </label>
        </div>

        <div class="tool-action-row">
          <button :disabled="!canExecute" @click="handleRunTool">
            {{ runningTool ? "执行中..." : "执行工具" }}
          </button>
        </div>
      </article>
    </div>

    <ToolResultViewer v-if="latestResult" :result="latestResult" />
  </section>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from "vue";

import ToolResultViewer from "@/components/tools/ToolResultViewer.vue";
import { callTool, createToolWorkspace, listToolWorkspaces, listTools } from "@/services/tools";

const workspace = ref(null);
const workspaceOptions = ref([]);
const selectedWorkspaceId = ref("");
const toolsEnabled = ref(false);
const availableTools = ref([]);
const loadingTools = ref(false);
const loadingWorkspaces = ref(false);
const creatingWorkspace = ref(false);
const runningTool = ref(false);
const selectedToolName = ref("list_dir");
const latestResult = ref(null);
const errorText = ref("");
const infoText = ref("");
const refreshingPanel = computed(() => loadingTools.value || loadingWorkspaces.value);

const workspaceForm = reactive({
  featureName: "tools",
  title: "工具沙箱",
});

const form = reactive({
  path: ".",
  encoding: "utf-8",
  command: "python -V",
  cwd: ".",
  timeoutSeconds: 30,
  query: "东京 5 日 旅行 攻略",
  maxResults: 5,
  content: "",
  overwrite: true,
});

const selectedToolMeta = computed(() => availableTools.value.find((item) => item.name === selectedToolName.value) || null);
const usesPath = computed(() => ["list_dir", "read_file", "write_file", "append_file", "make_dir"].includes(selectedToolName.value));
const usesEncoding = computed(() => ["read_file", "write_file", "append_file"].includes(selectedToolName.value));
const usesContent = computed(() => ["write_file", "append_file"].includes(selectedToolName.value));
const usesCommand = computed(() => selectedToolName.value === "run_command");
const usesCwd = computed(() => selectedToolName.value === "run_command");
const usesTimeout = computed(() => selectedToolName.value === "run_command");
const usesQuery = computed(() => selectedToolName.value === "web_search");
const usesMaxResults = computed(() => selectedToolName.value === "web_search");
const usesOverwrite = computed(() => selectedToolName.value === "write_file");
const pathPlaceholder = computed(() => (selectedToolName.value === "make_dir" ? "sandbox/output" : "notes.txt"));
const canExecute = computed(() => Boolean(workspace.value?.workspace_id) && Boolean(selectedToolName.value) && !runningTool.value);

watch(
  selectedToolName,
  (toolName) => {
    if (toolName === "list_dir") {
      form.path = ".";
      return;
    }
    if (toolName === "read_file") {
      form.path = "notes.txt";
      return;
    }
    if (toolName === "write_file") {
      form.path = "notes.txt";
      if (!form.content) {
        form.content = "Hello from BiliBrain tools.";
      }
      return;
    }
    if (toolName === "append_file") {
      form.path = "notes.txt";
      if (!form.content) {
        form.content = "\nAppended line.";
      }
      return;
    }
    if (toolName === "make_dir") {
      form.path = "sandbox/output";
      return;
    }
    if (toolName === "web_search") {
      form.query = form.query || "东京 5 日 旅行 攻略";
      form.maxResults = Number(form.maxResults) || 5;
      return;
    }
    form.command = form.command || "python -V";
    form.cwd = form.cwd || ".";
  },
  { immediate: true }
);

async function refreshTools() {
  loadingTools.value = true;
  errorText.value = "";
  try {
    const payload = await listTools();
    toolsEnabled.value = Boolean(payload.enabled);
    availableTools.value = Array.isArray(payload.tools) ? payload.tools : [];
    if (availableTools.value.length && !availableTools.value.some((item) => item.name === selectedToolName.value)) {
      selectedToolName.value = availableTools.value[0].name;
    }
    infoText.value = toolsEnabled.value
      ? `已载入 ${availableTools.value.length} 个工具。`
      : "后端当前未启用工具服务。";
  } catch (error) {
    errorText.value = error.message || "读取工具列表失败。";
  } finally {
    loadingTools.value = false;
  }
}

async function refreshWorkspaces() {
  loadingWorkspaces.value = true;
  errorText.value = "";
  try {
    const payload = await listToolWorkspaces({
      featureName: workspaceForm.featureName || "tools",
      limit: 50,
    });
    workspaceOptions.value = Array.isArray(payload.workspaces) ? payload.workspaces : [];
    if (selectedWorkspaceId.value && workspaceOptions.value.some((item) => item.workspace_id === selectedWorkspaceId.value)) {
      workspace.value = workspaceOptions.value.find((item) => item.workspace_id === selectedWorkspaceId.value) || null;
      return;
    }
    if (workspaceOptions.value.length) {
      selectedWorkspaceId.value = workspaceOptions.value[0].workspace_id;
      workspace.value = workspaceOptions.value[0];
    } else {
      selectedWorkspaceId.value = "";
      workspace.value = null;
    }
  } catch (error) {
    errorText.value = error.message || "读取工作区失败。";
  } finally {
    loadingWorkspaces.value = false;
  }
}

async function refreshPanel() {
  await Promise.all([refreshTools(), refreshWorkspaces()]);
}

async function handleCreateWorkspace() {
  creatingWorkspace.value = true;
  errorText.value = "";
  try {
    workspace.value = await createToolWorkspace({
      feature_name: workspaceForm.featureName || "tools",
      title: workspaceForm.title || "",
      actor: "workbench",
    });
    selectedWorkspaceId.value = workspace.value.workspace_id;
    await refreshWorkspaces();
    infoText.value = `工作区 ${workspace.value.display_name || workspace.value.workspace_id} 已就绪。`;
  } catch (error) {
    errorText.value = error.message || "创建工作区失败。";
  } finally {
    creatingWorkspace.value = false;
  }
}

function buildArguments() {
  if (selectedToolName.value === "list_dir") {
    return { path: form.path || "." };
  }
  if (selectedToolName.value === "read_file") {
    return { path: form.path || "", encoding: form.encoding || "utf-8" };
  }
  if (selectedToolName.value === "write_file") {
    return {
      path: form.path || "",
      encoding: form.encoding || "utf-8",
      content: form.content || "",
      overwrite: Boolean(form.overwrite),
    };
  }
  if (selectedToolName.value === "append_file") {
    return {
      path: form.path || "",
      encoding: form.encoding || "utf-8",
      content: form.content || "",
    };
  }
  if (selectedToolName.value === "make_dir") {
    return { path: form.path || "", parents: true, exist_ok: true };
  }
  if (selectedToolName.value === "web_search") {
    return {
      query: form.query || "",
      max_results: Number(form.maxResults) || 5,
    };
  }
  return {
    command: form.command || "",
    cwd: form.cwd || ".",
    timeout_seconds: Number(form.timeoutSeconds) || 30,
  };
}

async function handleRunTool() {
  if (!workspace.value?.workspace_id) {
    errorText.value = "请先创建或选择一个工作区。";
    return;
  }
  runningTool.value = true;
  errorText.value = "";
  latestResult.value = null;
  try {
    latestResult.value = await callTool({
      workspace_id: workspace.value.workspace_id,
      tool_name: selectedToolName.value,
      arguments: buildArguments(),
      actor: "workbench",
      approval_mode: "auto",
    });
    infoText.value = `${selectedToolName.value} completed.`;
  } catch (error) {
    errorText.value = error.message || "工具执行失败。";
  } finally {
    runningTool.value = false;
  }
}

watch(selectedWorkspaceId, (workspaceId) => {
  if (!workspaceId) {
    workspace.value = null;
    return;
  }
  workspace.value = workspaceOptions.value.find((item) => item.workspace_id === workspaceId) || null;
});

onMounted(() => {
  refreshPanel();
});
</script>

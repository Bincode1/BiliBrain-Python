<template>
  <section class="flex flex-col gap-4 p-4">
    <div class="grid gap-4 lg:grid-cols-2">
      <!-- Workspace card -->
      <Card>
        <CardHeader class="pb-3">
          <div class="flex items-center justify-between">
            <div>
              <span class="text-[10px] uppercase tracking-wider text-muted-foreground">工作区</span>
              <CardTitle class="text-base">工具工作区</CardTitle>
            </div>
            <Badge :variant="toolsEnabled ? 'default' : 'secondary'">{{ toolsEnabled ? "已启用" : "未启用" }}</Badge>
          </div>
        </CardHeader>
        <CardContent class="flex flex-col gap-3">
          <p class="text-xs text-muted-foreground">在当前工作台里手动创建一个工具工作区，然后调用文件或命令工具验证后端 runtime。</p>

          <div class="grid grid-cols-2 gap-2">
            <div class="flex flex-col gap-1">
              <label class="text-[10px] uppercase tracking-wider text-muted-foreground">功能标识</label>
              <Input v-model.trim="workspaceForm.featureName" placeholder="tools" />
            </div>
            <div class="flex flex-col gap-1">
              <label class="text-[10px] uppercase tracking-wider text-muted-foreground">工作区名称</label>
              <Input v-model.trim="workspaceForm.title" placeholder="工具沙箱" />
            </div>
          </div>

          <div class="flex gap-2">
            <Button :disabled="creatingWorkspace" @click="handleCreateWorkspace">{{ creatingWorkspace ? "创建中..." : "创建工作区" }}</Button>
            <Button variant="ghost" :disabled="refreshingPanel" @click="refreshPanel">{{ refreshingPanel ? "刷新中..." : "刷新面板" }}</Button>
          </div>

          <div class="flex flex-col gap-1">
            <label class="text-[10px] uppercase tracking-wider text-muted-foreground">当前工作区</label>
            <Select v-model="selectedWorkspaceId" :disabled="loadingWorkspaces || !workspaceOptions.length">
              <SelectTrigger>
                <SelectValue :placeholder="workspaceOptions.length ? '选择工作区' : '暂时还没有工作区'" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem v-for="item in workspaceOptions" :key="item.workspace_id" :value="item.workspace_id">
                  {{ item.display_name }}
                </SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div v-if="workspace" class="flex flex-col gap-0.5 text-xs text-muted-foreground">
            <span>工作区：<strong class="text-foreground">{{ workspace.display_name || workspace.workspace_id }}</strong></span>
            <span>编号：{{ workspace.workspace_id }}</span>
            <span v-if="workspace.root_path">根目录：{{ workspace.root_path }}</span>
          </div>
          <p v-if="errorText" class="text-xs text-destructive">{{ errorText }}</p>
          <p v-else-if="infoText" class="text-xs text-muted-foreground">{{ infoText }}</p>
        </CardContent>
      </Card>

      <!-- Executor card -->
      <Card>
        <CardHeader class="pb-3">
          <div class="flex items-center justify-between">
            <div>
              <span class="text-[10px] uppercase tracking-wider text-muted-foreground">执行器</span>
              <CardTitle class="text-base">运行工具</CardTitle>
            </div>
            <Badge variant="outline">{{ selectedToolMeta?.approval_mode || "auto" }}</Badge>
          </div>
        </CardHeader>
        <CardContent class="flex flex-col gap-3">
          <div class="flex flex-col gap-1">
            <label class="text-[10px] uppercase tracking-wider text-muted-foreground">工具</label>
            <Select v-model="selectedToolName">
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem v-for="item in availableTools" :key="item.name" :value="item.name">{{ item.name }}</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div class="grid grid-cols-2 gap-2">
            <div v-if="usesPath" class="flex flex-col gap-1">
              <label class="text-[10px] uppercase tracking-wider text-muted-foreground">路径</label>
              <Input v-model="form.path" :placeholder="pathPlaceholder" />
            </div>
            <div v-if="usesQuery" class="flex flex-col gap-1 col-span-2">
              <label class="text-[10px] uppercase tracking-wider text-muted-foreground">搜索词</label>
              <Input v-model="form.query" placeholder="东京 5 日 旅行 攻略" />
            </div>
            <div v-if="usesMaxResults" class="flex flex-col gap-1">
              <label class="text-[10px] uppercase tracking-wider text-muted-foreground">结果数</label>
              <Input v-model.number="form.maxResults" type="number" min="1" max="10" />
            </div>
            <div v-if="usesEncoding" class="flex flex-col gap-1">
              <label class="text-[10px] uppercase tracking-wider text-muted-foreground">编码</label>
              <Input v-model="form.encoding" placeholder="utf-8" />
            </div>
            <div v-if="usesCommand" class="flex flex-col gap-1 col-span-2">
              <label class="text-[10px] uppercase tracking-wider text-muted-foreground">命令</label>
              <Input v-model="form.command" placeholder="python -V" />
            </div>
            <div v-if="usesCwd" class="flex flex-col gap-1">
              <label class="text-[10px] uppercase tracking-wider text-muted-foreground">运行目录</label>
              <Input v-model="form.cwd" placeholder="." />
            </div>
            <div v-if="usesTimeout" class="flex flex-col gap-1">
              <label class="text-[10px] uppercase tracking-wider text-muted-foreground">超时（秒）</label>
              <Input v-model.number="form.timeoutSeconds" type="number" min="1" />
            </div>
          </div>

          <div v-if="usesContent" class="flex flex-col gap-1">
            <label class="text-[10px] uppercase tracking-wider text-muted-foreground">内容</label>
            <Textarea v-model="form.content" placeholder="写入到当前工作区文件中的正文..." rows="3" />
          </div>

          <div v-if="usesOverwrite" class="flex items-center gap-2">
            <Switch v-model:checked="form.overwrite" />
            <span class="text-xs">覆盖同名文件</span>
          </div>

          <Button :disabled="!canExecute" @click="handleRunTool">{{ runningTool ? "执行中..." : "执行工具" }}</Button>
        </CardContent>
      </Card>
    </div>

    <ToolResultViewer v-if="latestResult" :result="latestResult" />
  </section>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from "vue";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";

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

const workspaceForm = reactive({ featureName: "tools", title: "工具沙箱" });
const form = reactive({ path: ".", encoding: "utf-8", command: "python -V", cwd: ".", timeoutSeconds: 30, query: "东京 5 日 旅行 攻略", maxResults: 5, content: "", overwrite: true });

const selectedToolMeta = computed(() => availableTools.value.find((i) => i.name === selectedToolName.value) || null);
const usesPath = computed(() => ["list_dir", "read_file", "write_file", "append_file", "make_dir"].includes(selectedToolName.value));
const usesEncoding = computed(() => ["read_file", "write_file", "append_file"].includes(selectedToolName.value));
const usesContent = computed(() => ["write_file", "append_file"].includes(selectedToolName.value));
const usesCommand = computed(() => selectedToolName.value === "run_command");
const usesCwd = computed(() => selectedToolName.value === "run_command");
const usesTimeout = computed(() => selectedToolName.value === "run_command");
const usesQuery = computed(() => selectedToolName.value === "web_search");
const usesMaxResults = computed(() => selectedToolName.value === "web_search");
const usesOverwrite = computed(() => selectedToolName.value === "write_file");
const pathPlaceholder = computed(() => selectedToolName.value === "make_dir" ? "sandbox/output" : "notes.txt");
const canExecute = computed(() => Boolean(workspace.value?.workspace_id) && Boolean(selectedToolName.value) && !runningTool.value);

watch(selectedToolName, (toolName) => {
  const defaults = { list_dir: ".", read_file: "notes.txt", write_file: "notes.txt", append_file: "notes.txt", make_dir: "sandbox/output" };
  if (defaults[toolName]) form.path = defaults[toolName];
  if (toolName === "write_file" && !form.content) form.content = "Hello from BiliBrain tools.";
  if (toolName === "append_file" && !form.content) form.content = "\nAppended line.";
}, { immediate: true });

async function refreshTools() {
  loadingTools.value = true; errorText.value = "";
  try {
    const payload = await listTools();
    toolsEnabled.value = Boolean(payload.enabled);
    availableTools.value = Array.isArray(payload.tools) ? payload.tools : [];
    if (availableTools.value.length && !availableTools.value.some((i) => i.name === selectedToolName.value)) selectedToolName.value = availableTools.value[0].name;
    infoText.value = toolsEnabled.value ? `已载入 ${availableTools.value.length} 个工具。` : "后端当前未启用工具服务。";
  } catch (e) { errorText.value = e.message || "读取工具列表失败。"; }
  finally { loadingTools.value = false; }
}

async function refreshWorkspaces() {
  loadingWorkspaces.value = true; errorText.value = "";
  try {
    const payload = await listToolWorkspaces({ featureName: workspaceForm.featureName || "tools", limit: 50 });
    workspaceOptions.value = Array.isArray(payload.workspaces) ? payload.workspaces : [];
    if (selectedWorkspaceId.value && workspaceOptions.value.some((i) => i.workspace_id === selectedWorkspaceId.value)) {
      workspace.value = workspaceOptions.value.find((i) => i.workspace_id === selectedWorkspaceId.value) || null; return;
    }
    if (workspaceOptions.value.length) { selectedWorkspaceId.value = workspaceOptions.value[0].workspace_id; workspace.value = workspaceOptions.value[0]; }
    else { selectedWorkspaceId.value = ""; workspace.value = null; }
  } catch (e) { errorText.value = e.message || "读取工作区失败。"; }
  finally { loadingWorkspaces.value = false; }
}

async function refreshPanel() { await Promise.all([refreshTools(), refreshWorkspaces()]); }

async function handleCreateWorkspace() {
  creatingWorkspace.value = true; errorText.value = "";
  try {
    workspace.value = await createToolWorkspace({ feature_name: workspaceForm.featureName || "tools", title: workspaceForm.title || "", actor: "workbench" });
    selectedWorkspaceId.value = workspace.value.workspace_id;
    await refreshWorkspaces();
    infoText.value = `工作区 ${workspace.value.display_name || workspace.value.workspace_id} 已就绪。`;
  } catch (e) { errorText.value = e.message || "创建工作区失败。"; }
  finally { creatingWorkspace.value = false; }
}

function buildArguments() {
  if (selectedToolName.value === "list_dir") return { path: form.path || "." };
  if (selectedToolName.value === "read_file") return { path: form.path || "", encoding: form.encoding || "utf-8" };
  if (selectedToolName.value === "write_file") return { path: form.path || "", encoding: form.encoding || "utf-8", content: form.content || "", overwrite: Boolean(form.overwrite) };
  if (selectedToolName.value === "append_file") return { path: form.path || "", encoding: form.encoding || "utf-8", content: form.content || "" };
  if (selectedToolName.value === "make_dir") return { path: form.path || "", parents: true, exist_ok: true };
  if (selectedToolName.value === "web_search") return { query: form.query || "", max_results: Number(form.maxResults) || 5 };
  return { command: form.command || "", cwd: form.cwd || ".", timeout_seconds: Number(form.timeoutSeconds) || 30 };
}

async function handleRunTool() {
  if (!workspace.value?.workspace_id) { errorText.value = "请先创建或选择一个工作区。"; return; }
  runningTool.value = true; errorText.value = ""; latestResult.value = null;
  try {
    latestResult.value = await callTool({ workspace_id: workspace.value.workspace_id, tool_name: selectedToolName.value, arguments: buildArguments(), actor: "workbench", approval_mode: "auto" });
    infoText.value = `${selectedToolName.value} completed.`;
  } catch (e) { errorText.value = e.message || "工具执行失败。"; }
  finally { runningTool.value = false; }
}

watch(selectedWorkspaceId, (id) => { workspace.value = id ? workspaceOptions.value.find((i) => i.workspace_id === id) || null : null; });
onMounted(() => { refreshPanel(); });
</script>

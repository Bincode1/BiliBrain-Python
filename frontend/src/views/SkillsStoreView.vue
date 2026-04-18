<template>
  <section class="flex h-full flex-col gap-3 overflow-auto p-4">
    <!-- Header -->
    <header class="flex items-center gap-4 border-b border-border px-6 py-4">
      <div>
        <span class="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">技能目录</span>
        <h2 class="text-xl font-semibold">Skills</h2>
      </div>
      <div class="ml-auto flex gap-2">
        <Button size="sm" :disabled="refreshing" @click="refreshPanel()">{{ refreshing ? "刷新中..." : "刷新" }}</Button>
        <Button size="sm" variant="outline" :disabled="refreshing" @click="refreshPanel({ reload: true })">重新扫描</Button>
        <Button size="sm" @click="openCreateDialog">新建技能</Button>
      </div>
      <div class="flex gap-3 text-xs text-muted-foreground">
        <span>已发现 {{ skills.length }}</span>
        <span>已激活 {{ activeSkills.length }}</span>
      </div>
    </header>

    <!-- Status -->
    <p v-if="errorText" class="text-xs text-destructive">{{ errorText }}</p>

    <!-- Empty state -->
    <div v-if="!skills.length && !refreshing" class="flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-border py-16 text-center">
      <strong class="text-lg">还没有可展示的 Skills</strong>
      <p class="text-sm text-muted-foreground">先刷新一次，或检查技能目录配置。</p>
    </div>

    <div v-else-if="refreshing && !skills.length" class="flex items-center justify-center py-16 text-sm text-muted-foreground">正在读取技能列表...</div>

    <!-- Skill grid -->
    <div v-else class="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
      <Card
        v-for="item in skills"
        :key="item.name"
        class="overflow-hidden transition-all hover:shadow-md"
      >
        <CardHeader class="p-4 pb-2">
          <div class="flex items-center justify-between">
            <div>
              <h3 class="text-base font-semibold">{{ item.name }}</h3>
            </div>
            <Switch
              :model-value="item.active"
              @update:model-value="(value) => handleSkillToggle(item, value)"
              :disabled="activatingName === item.name"
            />
          </div>
        </CardHeader>
        <CardContent class="p-4 pt-2">
          <p class="mb-3 line-clamp-3 text-sm text-muted-foreground">{{ item.description || "暂无描述" }}</p>
          <div class="flex flex-wrap gap-2 text-xs text-muted-foreground">
            <span>工具 {{ item.allowed_tools?.length || 0 }}</span>
            <span>{{ item.allow_model_invocation ? "可直接调用" : "仅手动使用" }}</span>
          </div>
          <p v-if="item.when_to_use" class="mt-3 text-xs text-muted-foreground">适用场景：{{ item.when_to_use }}</p>
          <Button
            size="sm"
            class="mt-4 w-full"
            @click="openSkillDetail(item)"
          >
            查看详情
          </Button>
        </CardContent>
      </Card>
    </div>

    <!-- Skill detail modal -->
    <Dialog v-model:open="skillDetailOpen">
      <DialogContent class="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{{ selectedSkill?.name }} 技能详情</DialogTitle>
        </DialogHeader>
        <div class="space-y-4">
          <div class="space-y-2">
            <h4 class="text-sm font-semibold">描述</h4>
            <p class="text-sm text-muted-foreground">{{ selectedSkill?.description || "暂无描述" }}</p>
          </div>
          <div v-if="selectedSkill?.when_to_use" class="space-y-2">
            <h4 class="text-sm font-semibold">适用场景</h4>
            <p class="text-sm text-muted-foreground">{{ selectedSkill.when_to_use }}</p>
          </div>
          <div v-if="selectedSkill?.input_hint" class="space-y-2">
            <h4 class="text-sm font-semibold">输入提示</h4>
            <p class="text-sm text-muted-foreground">{{ selectedSkill.input_hint }}</p>
          </div>
          <div v-if="selectedSkill?.examples?.length" class="space-y-2">
            <h4 class="text-sm font-semibold">示例</h4>
            <div class="flex flex-col gap-2">
              <p v-for="example in selectedSkill.examples" :key="example" class="rounded-md bg-muted/50 px-3 py-2 text-xs text-foreground">{{ example }}</p>
            </div>
          </div>
          <div class="space-y-2">
            <h4 class="text-sm font-semibold">允许工具</h4>
            <div v-if="selectedSkill?.allowed_tools?.length" class="flex flex-wrap gap-1">
              <Badge v-for="tool in selectedSkill.allowed_tools" :key="tool" variant="secondary" class="text-[10px]">{{ tool }}</Badge>
            </div>
            <p v-else class="text-xs text-muted-foreground">当前没有声明允许工具。</p>
          </div>
          <div class="space-y-2">
            <h4 class="text-sm font-semibold">资源</h4>
            <div v-if="selectedSkill?.resources?.length" class="flex flex-wrap gap-1">
              <Badge v-for="resource in selectedSkill.resources" :key="resource" variant="outline" class="text-[10px]">{{ resource }}</Badge>
            </div>
            <p v-else class="text-xs text-muted-foreground">当前没有附带资源说明。</p>
          </div>
          <div class="space-y-2">
            <h4 class="text-sm font-semibold">状态</h4>
            <div class="flex items-center gap-2">
              <span class="text-sm">{{ selectedSkill?.active ? '已激活' : '未激活' }}</span>
              <Switch
                :model-value="selectedSkillActive"
                @update:model-value="(value) => {
                  selectedSkillActive = value;
                  handleSkillDetailToggle();
                }"
                :disabled="activatingName === selectedSkill?.name"
              />
            </div>
          </div>
          <div class="space-y-2">
            <h4 class="text-sm font-semibold">指令正文</h4>
            <div
              v-if="selectedSkill?.body"
              class="prose prose-sm max-w-none max-h-72 overflow-auto rounded-md bg-muted/50 p-3 text-foreground"
              v-html="renderMarkdown(selectedSkill.body)"
            />
            <p v-else class="text-xs text-muted-foreground">暂无指令内容。</p>
          </div>
        </div>
        <DialogFooter class="mt-4">
          <Button variant="outline" @click="skillDetailOpen = false">关闭</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

    <!-- Create skill modal -->
    <Dialog v-model:open="createDialogOpen">
      <DialogContent class="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>新建技能</DialogTitle>
        </DialogHeader>
        <div class="space-y-4">
          <div class="space-y-2">
            <label class="text-sm font-medium">名称</label>
            <Input v-model="createForm.name" placeholder="例如: my-custom-skill" :disabled="creating" />
          </div>
          <div class="space-y-2">
            <label class="text-sm font-medium">描述</label>
            <Input v-model="createForm.description" placeholder="简要描述该技能的用途" :disabled="creating" />
          </div>
          <div class="space-y-2">
            <label class="text-sm font-medium">指令正文</label>
            <Textarea
              v-model="createForm.body"
              placeholder="编写该技能的完整指令，供 AI 执行时参考..."
              rows="8"
              :disabled="creating"
            />
          </div>
          <p v-if="createError" class="text-xs text-destructive">{{ createError }}</p>
        </div>
        <DialogFooter class="mt-4">
          <Button variant="outline" @click="createDialogOpen = false" :disabled="creating">取消</Button>
          <Button :disabled="creating || !createForm.name || !createForm.description || !createForm.body" @click="handleCreate">
            {{ creating ? "创建中..." : "创建" }}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from "vue";

import { renderMarkdown } from "@/utils/chat";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";

import { activateSkill, createSkill, deactivateSkill, getSkill, listSkills } from "@/services/skills";

const skills = ref([]);
const activeSkills = ref([]);
const selectedSkill = ref(null);
const skillDetailOpen = ref(false);
const refreshing = ref(false);
const activatingName = ref("");
const errorText = ref("");
const createDialogOpen = ref(false);
const creating = ref(false);
const createError = ref("");
const createForm = ref({ name: "", description: "", body: "" });

const selectedSkillActive = computed({
  get: () => selectedSkill.value?.active || false,
  set: (value) => {
    if (selectedSkill.value) {
      selectedSkill.value.active = value;
    }
  }
});

function openSkillDetail(skill) {
  selectedSkill.value = skill;
  skillDetailOpen.value = true;
  loadSkillDetail(skill.name);
}

async function loadSkillDetail(name) {
  try {
    const detail = await getSkill(name);
    selectedSkill.value = { ...selectedSkill.value, ...detail };
  } catch {
    // 静默失败，使用列表中的基础数据
  }
}

async function refreshPanel(options = {}) {
  refreshing.value = true;
  errorText.value = "";
  try {
    const payload = await listSkills({
      reload: Boolean(options.reload),
    });
    skills.value = Array.isArray(payload.skills) ? payload.skills : [];
    activeSkills.value = Array.isArray(payload.active_skills) ? payload.active_skills : [];
  } catch (error) {
    errorText.value = error.message || "读取技能失败。";
  } finally {
    refreshing.value = false;
  }
}

async function handleSkillToggle(item, value) {
  if (!item) return;
  const originalActive = item.active;
  activatingName.value = item.name;
  errorText.value = "";
  try {
    if (value) {
      await activateSkill({ name: item.name, actor: "workbench" });
      item.active = true;
    } else {
      await deactivateSkill({ name: item.name, actor: "workbench" });
      item.active = false;
    }
    await refreshPanel();
  } catch (error) {
    errorText.value = error.message || "操作技能失败。";
    item.active = originalActive;
  } finally {
    activatingName.value = "";
  }
}

async function handleSkillDetailToggle() {
  if (!selectedSkill.value) return;
  handleSkillToggle(selectedSkill.value, selectedSkillActive.value);
}

function openCreateDialog() {
  createForm.value = { name: "", description: "", body: "" };
  createError.value = "";
  createDialogOpen.value = true;
}

async function handleCreate() {
  creating.value = true;
  createError.value = "";
  try {
    await createSkill(createForm.value);
    createDialogOpen.value = false;
    await refreshPanel({ reload: true });
  } catch (error) {
    createError.value = error.message || "创建技能失败。";
  } finally {
    creating.value = false;
  }
}

onMounted(() => { refreshPanel(); });
</script>

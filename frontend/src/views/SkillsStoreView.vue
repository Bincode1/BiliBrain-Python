<template>
  <section class="collection-stage skills-library-page">
    <section class="skills-library-toolbar">
      <label class="market-session-field">
        <span>会话</span>
        <input v-model.trim="sessionId" placeholder="skills-session-1" />
      </label>
      <div class="skills-library-toolbar-actions">
        <button type="button" :disabled="refreshing" @click="refreshPanel()">
          {{ refreshing ? "刷新中..." : "刷新" }}
        </button>
        <button class="ghost-button" type="button" :disabled="refreshing" @click="refreshPanel({ reload: true })">
          重新扫描
        </button>
      </div>
      <div class="skills-library-toolbar-meta">
        <span class="skills-library-toolbar-stat">已发现 {{ skills.length }} 个</span>
        <span class="skills-library-toolbar-stat">当前激活 {{ activeSkills.length }} 个</span>
      </div>
      <p v-if="errorText" class="tool-error-text">{{ errorText }}</p>
      <p v-else class="skills-library-toolbar-note">{{ infoText || "这里会展示当前会话能用的全部技能。" }}</p>
    </section>

    <section v-if="activeSkills.length" class="skills-library-active-strip">
      <span class="skills-library-active-label">当前会话</span>
      <button
        v-for="item in activeSkills"
        :key="`active:${item.source}:${item.name}`"
        type="button"
        class="market-inline-chip"
        @click="openSkill(item.name)"
      >
        {{ item.name }}
      </button>
    </section>

    <section v-if="!skills.length && !refreshing" class="collection-empty-panel">
      <strong>还没有可展示的 Skills</strong>
      <p>先刷新一次，或检查当前会话和技能目录。</p>
    </section>

    <div v-else-if="refreshing && !skills.length" class="collection-empty-panel">正在读取技能列表...</div>

    <section v-else class="collection-video-grid skills-library-grid">
      <article
        v-for="item in skills"
        :key="`${item.source}:${item.name}`"
        class="collection-video-card skills-library-card"
        :class="{
          active: selectedSkill?.name === item.name,
        }"
      >
        <button class="skills-library-cover" type="button" @click="openSkill(item.name)">
          <span class="skills-library-cover-kicker">{{ formatSource(item.source) }}</span>
          <strong>{{ item.name }}</strong>
        </button>

        <div class="collection-video-copy">
          <div class="collection-video-top">
            <span class="collection-video-state" :class="skillStatusTone(item)">
              {{ skillStatusLabel(item) }}
            </span>
            <span class="skills-library-mini-meta">资源 {{ item.resources?.length || 0 }}</span>
          </div>

          <button class="collection-video-title" type="button" @click="openSkill(item.name)">
            {{ item.name }}
          </button>

          <p class="skills-library-description">{{ item.description || "暂无描述" }}</p>

          <div class="collection-video-meta skills-library-meta">
            <span>工具 {{ item.allowed_tools?.length || 0 }}</span>
            <span>{{ item.allow_model_invocation ? "可直接调用" : "仅手动使用" }}</span>
          </div>
        </div>

        <div v-if="selectedSkill?.name === item.name" class="collection-video-actions skills-library-actions">
          <div class="skills-library-detail-block">
            <span class="page-section-kicker">允许工具</span>
            <div v-if="item.allowed_tools?.length" class="skills-library-token-list">
              <span v-for="tool in item.allowed_tools" :key="tool" class="skills-library-token">
                {{ tool }}
              </span>
            </div>
            <p v-else class="skills-library-muted">当前没有声明允许工具。</p>
          </div>

          <div class="skills-library-detail-block">
            <span class="page-section-kicker">资源</span>
            <div v-if="item.resources?.length" class="skills-library-token-list">
              <span v-for="resource in item.resources" :key="resource" class="skills-library-token muted">
                {{ resource }}
              </span>
            </div>
            <p v-else class="skills-library-muted">当前没有附带资源说明。</p>
          </div>

          <button type="button" :disabled="!canActivate(item)" @click="handleActivateSkill(item)">
            {{ activatingName === item.name ? "激活中..." : "激活到当前会话" }}
          </button>
        </div>
      </article>
    </section>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from "vue";

import { activateSkill, getSkillSession, listSkills } from "@/services/skills";

const sessionId = ref("skills-session-1");
const skills = ref([]);
const activeSkills = ref([]);
const selectedSkillName = ref("");
const refreshing = ref(false);
const activatingName = ref("");
const errorText = ref("");
const infoText = ref("");

const selectedSkill = computed(() => skills.value.find((item) => item.name === selectedSkillName.value) || null);

function formatSource(source) {
  if (source === "system") return "系统";
  if (source === "user") return "用户";
  if (source === "repo") return "项目";
  return "技能";
}

function skillStatusLabel(item) {
  if (item.active) return "已激活";
  if (item.allow_model_invocation) return "可用";
  return "手动";
}

function skillStatusTone(item) {
  if (item.active) return "done";
  if (item.allow_model_invocation) return "processing";
  return "pending";
}

function openSkill(name) {
  selectedSkillName.value = name;
}

function canActivate(item) {
  return Boolean(item && sessionId.value && !activatingName.value);
}

async function refreshPanel(options = {}) {
  refreshing.value = true;
  errorText.value = "";
  try {
    const payload = await listSkills({
      sessionId: sessionId.value || undefined,
      reload: Boolean(options.reload),
    });
    skills.value = Array.isArray(payload.skills) ? payload.skills : [];

    const sessionPayload = sessionId.value
      ? await getSkillSession(sessionId.value)
      : { active_skills: [] };
    activeSkills.value = Array.isArray(sessionPayload.active_skills) ? sessionPayload.active_skills : [];

    const activeNames = new Set(activeSkills.value.map((item) => item.name));
    skills.value = skills.value.map((item) => ({
      ...item,
      active: activeNames.has(item.name),
    }));

    if (selectedSkillName.value && !skills.value.some((item) => item.name === selectedSkillName.value)) {
      selectedSkillName.value = "";
    }
    if (!selectedSkillName.value) {
      selectedSkillName.value = activeSkills.value[0]?.name || skills.value[0]?.name || "";
    }

    infoText.value = `会话 ${sessionId.value || "未设置"} 已同步。`;
  } catch (error) {
    errorText.value = error.message || "读取技能失败。";
  } finally {
    refreshing.value = false;
  }
}

async function handleActivateSkill(item) {
  if (!item || !sessionId.value) {
    return;
  }
  activatingName.value = item.name;
  errorText.value = "";
  try {
    await activateSkill({
      name: item.name,
      session_id: sessionId.value,
      actor: "workbench",
    });
    await refreshPanel();
    infoText.value = `${item.name} 已激活到当前会话。`;
  } catch (error) {
    errorText.value = error.message || "激活技能失败。";
  } finally {
    activatingName.value = "";
  }
}

onMounted(() => {
  refreshPanel();
});
</script>

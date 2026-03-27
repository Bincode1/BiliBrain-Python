<template>
  <section class="market-list-page tools-list-page">
    <header class="market-list-header">
      <div class="market-list-copy">
        <span class="page-section-kicker">工具目录</span>
        <h2>Tools</h2>
      </div>
      <div class="market-inline-bar compact-tools-summary">
        <span>可用 {{ readyCount }}</span>
        <span>分类 {{ categoryCount }}</span>
        <span>规划中 {{ plannedCount }}</span>
      </div>
    </header>

    <div class="market-list">
      <button
        v-for="item in toolsCatalog"
        :key="item.id"
        type="button"
        class="market-list-item"
        @click="selectedToolId = item.id"
      >
        <div class="market-list-main">
          <div class="market-list-title">
            <strong>{{ item.name }}</strong>
            <p>{{ item.description }}</p>
          </div>
          <div class="market-list-meta">
            <span class="market-status-chip">{{ item.category }}</span>
            <span class="market-status-chip" :class="item.badgeTone">{{ item.status }}</span>
          </div>
        </div>
      </button>
    </div>

    <div v-if="selectedTool" class="market-detail-overlay" @click.self="selectedToolId = ''">
      <article class="market-detail-modal market-detail-modal-wide">
        <div class="market-detail-head">
          <div>
            <span class="page-section-kicker">工具详情</span>
            <h3>{{ selectedTool.name }}</h3>
          </div>
          <button class="ghost-button" type="button" @click="selectedToolId = ''">关闭</button>
        </div>

        <div class="market-detail-tags">
          <span class="market-status-chip">{{ selectedTool.category }}</span>
          <span class="market-status-chip" :class="selectedTool.badgeTone">{{ selectedTool.status }}</span>
        </div>

        <p class="market-detail-copy">{{ selectedTool.description }}</p>

        <div class="market-detail-section">
          <span class="page-section-kicker">能力</span>
          <div class="market-chip-list">
            <span v-for="item in selectedTool.highlights" :key="item" class="market-inline-chip static">{{ item }}</span>
          </div>
        </div>

        <WorkspaceToolPanel v-if="interactiveToolIds.has(selectedTool.id)" />
      </article>
    </div>
  </section>
</template>

<script setup>
import { computed, ref } from "vue";

import WorkspaceToolPanel from "@/components/tools/WorkspaceToolPanel.vue";
import { toolsCatalog } from "@/config/toolsCatalog";

const readyCount = computed(() => toolsCatalog.filter((item) => item.status === "已接入" || item.status === "可用").length);
const categoryCount = computed(() => new Set(toolsCatalog.map((item) => item.category)).size);
const plannedCount = computed(() => toolsCatalog.filter((item) => item.status === "规划中").length);
const selectedToolId = ref("");
const interactiveToolIds = new Set(["workspace-filesystem", "workspace-command-runner", "web-search"]);
const selectedTool = computed(() => toolsCatalog.find((item) => item.id === selectedToolId.value) || null);
</script>

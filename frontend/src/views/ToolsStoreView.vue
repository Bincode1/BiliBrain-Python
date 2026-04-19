<template>
  <section class="flex h-full flex-col gap-3 overflow-auto p-3">
    <!-- Header -->
    <header class="flex items-center gap-4 border-b border-border px-4 py-3">
      <div>
        <span class="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">工具目录</span>
        <h2 class="text-lg font-semibold">Tools</h2>
      </div>
      <div class="ml-auto flex gap-3 text-xs text-muted-foreground">
        <span>可用 {{ readyCount }}</span>
        <span>分类 {{ categoryCount }}</span>
        <span>规划中 {{ plannedCount }}</span>
      </div>
    </header>

    <!-- Tool list -->
    <div class="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
      <Card
        v-for="item in toolsCatalog"
        :key="item.id"
        class="cursor-pointer transition-all hover:shadow-md"
        @click="selectedToolId = item.id"
      >
        <CardContent class="p-3">
          <div class="flex items-start justify-between gap-2">
            <div>
              <strong class="text-sm">{{ item.name }}</strong>
              <p class="mt-1 text-xs text-muted-foreground line-clamp-2">{{ item.description }}</p>
            </div>
            <div class="flex shrink-0 flex-col gap-1">
              <Badge variant="outline">{{ item.category }}</Badge>
              <Badge :variant="item.badgeTone === 'done' ? 'default' : 'secondary'">{{ item.status }}</Badge>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>

    <!-- Detail overlay -->
    <Dialog :open="Boolean(selectedTool)" @update:open="(v) => !v && (selectedToolId = '')">
      <DialogContent class="max-w-3xl">
        <DialogHeader>
          <div class="flex items-center gap-2">
            <Badge variant="outline">{{ selectedTool?.category }}</Badge>
            <Badge :variant="selectedTool?.badgeTone === 'done' ? 'default' : 'secondary'">{{ selectedTool?.status }}</Badge>
          </div>
          <DialogTitle>{{ selectedTool?.name }}</DialogTitle>
          <DialogDescription>{{ selectedTool?.description }}</DialogDescription>
        </DialogHeader>

        <div v-if="selectedTool?.highlights?.length" class="flex flex-wrap gap-2">
          <span v-for="h in selectedTool.highlights" :key="h" class="rounded-full bg-muted px-2 py-0.5 text-[11px]">{{ h }}</span>
        </div>

        <div v-if="selectedTool && interactiveToolIds.has(selectedTool.id)" class="mt-2">
          <WorkspaceToolPanel />
        </div>
      </DialogContent>
    </Dialog>
  </section>
</template>

<script setup>
import { computed, ref } from "vue";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";

import WorkspaceToolPanel from "@/components/tools/WorkspaceToolPanel.vue";
import { toolsCatalog } from "@/config/toolsCatalog";

const readyCount = computed(() => toolsCatalog.filter((i) => i.status === "已接入" || i.status === "可用").length);
const categoryCount = computed(() => new Set(toolsCatalog.map((i) => i.category)).size);
const plannedCount = computed(() => toolsCatalog.filter((i) => i.status === "规划中").length);
const selectedToolId = ref("");
const interactiveToolIds = new Set(["workspace-filesystem", "workspace-command-runner", "web-search"]);
const selectedTool = computed(() => toolsCatalog.find((i) => i.id === selectedToolId.value) || null);
</script>

<template>
  <Dialog :open="documentViewerOpen" @update:open="(v) => { if (!v) store.closeDocumentViewer() }">
    <DialogContent class="max-w-3xl max-h-[calc(100vh-48px)] flex flex-col overflow-hidden">
      <DialogHeader>
        <div class="flex items-start justify-between gap-4">
          <div class="min-w-0">
            <DialogDescription class="text-[10px] uppercase tracking-wider text-muted-foreground">当前视频资料</DialogDescription>
            <DialogTitle class="line-clamp-1">{{ documentViewerTitle }}</DialogTitle>
          </div>
        </div>
      </DialogHeader>

      <Tabs :model-value="documentViewerMode" @update:model-value="store.switchDocumentViewerMode" class="flex flex-col min-h-0 flex-1">
        <div class="flex items-center gap-4 shrink-0">
          <TabsList>
            <TabsTrigger value="summary">摘要</TabsTrigger>
            <TabsTrigger value="transcript">转写</TabsTrigger>
          </TabsList>
          <Badge :variant="documentViewerMode === 'summary' ? 'default' : 'secondary'" class="text-[10px]">
            {{ documentViewerMode === "summary" ? "视频摘要" : "完整转写" }}
          </Badge>
          <span v-if="activeDocumentPane.meta" class="text-[11px] text-muted-foreground">{{ activeDocumentPane.meta }}</span>
        </div>

        <TabsContent value="summary" class="min-h-0 flex-1 mt-3">
          <div v-if="activeDocumentPane.loading" class="flex items-center justify-center py-10 text-sm text-muted-foreground">正在加载内容...</div>
          <div v-else-if="activeDocumentPane.error" class="rounded-lg bg-destructive/10 px-4 py-3 text-sm text-destructive">{{ activeDocumentPane.error }}</div>
          <div v-else-if="activeDocumentPane.text" class="h-full max-h-[min(60vh,640px)] overflow-auto rounded-lg border border-border bg-card p-5">
            <div class="prose prose-sm max-w-none" v-html="renderMarkdown(activeDocumentPane.text)"></div>
          </div>
          <div v-else class="flex items-center justify-center py-10 text-sm text-muted-foreground">暂无摘要内容</div>
        </TabsContent>

        <TabsContent value="transcript" class="min-h-0 flex-1 mt-3">
          <div v-if="activeDocumentPane.loading" class="flex items-center justify-center py-10 text-sm text-muted-foreground">正在加载内容...</div>
          <div v-else-if="activeDocumentPane.error" class="rounded-lg bg-destructive/10 px-4 py-3 text-sm text-destructive">{{ activeDocumentPane.error }}</div>
          <pre v-else-if="activeDocumentPane.text" class="h-full max-h-[min(60vh,640px)] overflow-auto whitespace-pre-wrap rounded-lg border border-border bg-card p-5 text-sm leading-relaxed">{{ activeDocumentPane.text }}</pre>
          <div v-else class="flex items-center justify-center py-10 text-sm text-muted-foreground">暂无转写内容</div>
        </TabsContent>
      </Tabs>
    </DialogContent>
  </Dialog>
</template>

<script setup>
import { storeToRefs } from "pinia";

import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

import { useDocumentViewerStore } from "@/stores/documentViewer";
import { renderMarkdown } from "@/utils/chat";

const store = useDocumentViewerStore();
const { activeDocumentPane, documentViewerMode, documentViewerOpen, documentViewerTitle } = storeToRefs(store);
</script>

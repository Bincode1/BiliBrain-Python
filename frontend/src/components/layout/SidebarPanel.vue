<template>
  <aside class="flex h-full w-[280px] shrink-0 flex-col gap-2.5 overflow-hidden border-r border-border bg-background p-3">
    <!-- Identity card -->
    <div class="flex items-center justify-between rounded-lg bg-card border border-border px-3 py-2.5">
      <div class="flex items-center gap-2.5">
        <div class="flex h-7 w-7 items-center justify-center rounded-lg text-[10px] font-bold text-white" :style="{ background: `color-mix(in oklab, var(--primary) 78%, white 22%)` }">档</div>
        <div class="flex flex-col">
          <span class="text-sm font-semibold leading-tight">收藏夹</span>
          <span class="text-[10px] text-muted-foreground">内容整理</span>
        </div>
      </div>
      <div class="flex flex-col items-end gap-0.5">
        <span class="text-[10px] text-muted-foreground">B 站账号</span>
        <span class="max-w-[110px] truncate text-[11px] font-medium">{{ session.loggedIn ? session.userName : "未登录" }}</span>
      </div>
    </div>
    <Button variant="outline" size="sm" class="w-full text-xs" @click="authStore.startQrLogin">
      {{ session.loggedIn ? "换账号" : "扫码登录" }}
    </Button>

    <!-- Settings strip -->
    <div class="rounded-lg bg-card border border-border px-3 py-2 space-y-2">
      <div class="flex items-center gap-2">
        <span class="shrink-0 text-[11px] text-muted-foreground">时长</span>
        <Input v-model="processingSettings.max_video_minutes" type="number" min="1" max="300" class="h-6 w-14 text-xs" />
        <Button size="sm" class="ml-auto h-6 px-2.5 text-[11px]" :disabled="processingSettings.saving" @click="foldersStore.saveSettings">保存</Button>
        <Button variant="outline" size="sm" class="h-6 px-2.5 text-[11px] text-destructive border-destructive/30 hover:bg-destructive/10" @click="foldersStore.resetAllProcessedContent">重置</Button>
      </div>
    </div>

    <!-- Status messages -->
    <div v-if="settingsStatus.show" :class="['text-[11px] px-2 py-1 rounded-lg break-words', settingsStatus.error ? 'text-destructive' : 'text-muted-foreground']">
      {{ settingsStatus.message }}
    </div>
    <div v-if="syncStatus.show" :class="['text-[11px] px-2 py-1 rounded-lg break-words', syncStatus.error ? 'text-destructive' : 'text-muted-foreground']">
      {{ syncStatus.message }}
    </div>

    <!-- Folders -->
    <div class="text-[10px] font-medium uppercase tracking-wider text-muted-foreground px-1">收藏夹目录</div>

    <ScrollArea v-if="folders.length" class="flex-1">
      <div class="flex flex-col gap-1 pr-2">
        <div
          v-for="folder in folders"
          :key="folder.folder_id"
          class="group cursor-pointer rounded-lg border px-2.5 py-2 transition-all"
          :class="selectedFolderId === String(folder.folder_id) ? 'border-primary/40 bg-primary/5 shadow-sm' : 'border-border hover:bg-secondary'"
          @click="foldersStore.openFolder(folder)"
        >
          <div class="flex items-center justify-between gap-2">
            <strong class="text-[13px] font-semibold truncate leading-tight">{{ folder.title }}</strong>
          </div>
          <div class="mt-0.5 flex items-center justify-between">
            <span class="text-[10px] text-muted-foreground">{{ folder.media_count }} 个视频 · 已入库 {{ folder.synced_videos || 0 }}</span>
          </div>
          <div class="mt-1.5 flex gap-1.5">
            <button
              class="inline-flex items-center rounded-md bg-secondary px-2 py-0.5 text-[11px] font-medium text-secondary-foreground hover:bg-primary/10 hover:text-primary transition-colors"
              @click.stop="searchStore.openFolderSearch(folder)"
            >搜 B 站</button>
            <button
              class="inline-flex items-center rounded-md bg-secondary px-2 py-0.5 text-[11px] font-medium text-secondary-foreground hover:bg-primary/10 hover:text-primary transition-colors"
              @click.stop="foldersStore.syncFolder(folder)"
            >同步元数据</button>
          </div>
        </div>
      </div>
    </ScrollArea>

    <!-- Empty state -->
    <div v-else class="flex flex-1 flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-border px-4 py-6 text-center">
      <span class="text-[10px] uppercase tracking-wider text-muted-foreground">{{ session.loggedIn ? "收藏目录" : "第一步" }}</span>
      <strong class="text-xs">{{ session.loggedIn ? "还没有收藏夹目录" : "先扫码登录" }}</strong>
      <p class="text-[11px] text-muted-foreground">{{ session.loggedIn ? "刷新后这里会出现你的收藏夹列表。" : "登录后自动拉取你的收藏夹。" }}</p>
      <Button v-if="session.loggedIn" variant="outline" size="sm" @click="foldersStore.loadFolders">刷新目录</Button>
      <Button v-else size="sm" @click="authStore.startQrLogin">扫码登录</Button>
    </div>
  </aside>
</template>

<script setup>
import { storeToRefs } from "pinia";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";

import { useAuthStore } from "@/stores/auth";
import { useFolderSearchStore } from "@/stores/folderSearch";
import { useFoldersStore } from "@/stores/folders";

const authStore = useAuthStore();
const foldersStore = useFoldersStore();
const searchStore = useFolderSearchStore();
const { session } = storeToRefs(authStore);
const { folders, processingSettings, selectedFolderId, settingsStatus, syncStatus } = storeToRefs(foldersStore);
</script>

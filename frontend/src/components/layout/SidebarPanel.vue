<template>
  <aside class="flex h-full w-[272px] shrink-0 flex-col gap-2 overflow-hidden border-r border-border bg-background p-2.5">
    <!-- Identity card -->
    <div class="flex items-center justify-between rounded-lg border border-border bg-card px-3 py-2.5">
      <div class="flex items-center gap-2">
        <div class="flex h-7 w-7 items-center justify-center rounded-lg text-[10px] font-bold text-white" :style="{ background: `color-mix(in oklab, var(--primary) 78%, white 22%)` }">档</div>
        <div class="flex flex-col">
          <span class="text-[13px] font-semibold leading-tight">收藏夹</span>
          <span class="text-[12px] font-medium text-foreground/82">内容整理</span>
        </div>
      </div>
      <div class="flex flex-col items-end gap-0.5">
        <span class="text-[12px] font-medium text-foreground/78">B 站账号</span>
        <span class="max-w-[110px] truncate text-[12px] font-medium text-foreground">{{ session.loggedIn ? session.userName : "未登录" }}</span>
      </div>
    </div>
    <Button variant="outline" size="sm" class="w-full text-xs" @click="authStore.startQrLogin">
      {{ session.loggedIn ? "换账号" : "扫码登录" }}
    </Button>

    <!-- Settings strip -->
    <div class="space-y-2 rounded-lg border border-border bg-card px-3 py-2.5">
      <div class="grid grid-cols-[auto_minmax(0,72px)_auto_auto] items-center gap-2">
        <span class="text-[13px] font-medium text-foreground/78">时长</span>
        <Input
          v-model="processingSettings.max_video_minutes"
          type="number"
          min="1"
          max="300"
          class="h-7 min-w-0 w-full px-2 text-center text-[13px] font-medium [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none"
        />
        <Button size="sm" class="ml-auto h-6 px-2.5 text-[11px]" :disabled="processingSettings.saving" @click="foldersStore.saveSettings">保存</Button>
        <Button variant="outline" size="sm" class="h-6 px-2.5 text-[11px] text-destructive border-destructive/30 hover:bg-destructive/10" @click="foldersStore.resetAllProcessedContent">重置</Button>
      </div>
    </div>

    <!-- Status messages -->
    <div v-if="settingsStatus.show" :class="['rounded-lg px-2.5 py-1.5 text-[12px] break-words', settingsStatus.error ? 'bg-destructive/8 text-destructive' : 'bg-secondary/70 text-foreground/78']">
      {{ settingsStatus.message }}
    </div>
    <div v-if="syncStatus.show" :class="['rounded-lg px-2.5 py-1.5 text-[12px] break-words', syncStatus.error ? 'bg-destructive/8 text-destructive' : 'bg-secondary/70 text-foreground/78']">
      {{ syncStatus.message }}
    </div>

    <!-- Folders -->
    <div class="px-1 text-[11px] font-semibold uppercase tracking-wider text-foreground/76">收藏夹目录</div>

    <ScrollArea v-if="folders.length" class="flex-1">
      <div class="flex flex-col gap-1 pr-1.5">
        <div
          v-for="folder in folders"
          :key="folder.folder_id"
          class="group cursor-pointer rounded-lg border border-border px-2.5 py-2.5 transition-all duration-150 hover:-translate-y-px hover:bg-[color-mix(in_oklab,var(--primary)_4%,white)] hover:shadow-[var(--shadow-soft)]"
          :class="selectedFolderId === String(folder.folder_id) ? 'bg-[color-mix(in_oklab,var(--primary)_4%,white)] shadow-[var(--shadow-soft)]' : 'bg-card'"
          @click="foldersStore.openFolder(folder)"
        >
          <div class="flex items-center justify-between gap-2">
            <strong class="truncate text-[14px] font-semibold leading-tight text-foreground">{{ folder.title }}</strong>
          </div>
          <div class="mt-0.5 flex items-center justify-between">
            <span class="text-[12px] font-medium text-foreground/76">{{ folder.media_count }} 个视频 · 已入库 {{ folder.synced_videos || 0 }}</span>
          </div>
          <div class="mt-1 flex gap-1.5">
            <button
              class="inline-flex items-center rounded-md bg-secondary/90 px-2 py-1 text-[12px] font-medium text-foreground/88 transition-colors hover:bg-accent hover:text-primary"
              @click.stop="searchStore.openFolderSearch(folder)"
            >搜 B 站</button>
            <button
              class="inline-flex items-center rounded-md bg-secondary/90 px-2 py-1 text-[12px] font-medium text-foreground/88 transition-colors hover:bg-accent hover:text-primary"
              @click.stop="foldersStore.syncFolder(folder)"
            >同步元数据</button>
          </div>
        </div>
      </div>
    </ScrollArea>

    <!-- Empty state -->
    <div v-else class="flex flex-1 flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-border px-4 py-6 text-center">
      <span class="text-[11px] font-semibold uppercase tracking-wider text-foreground/74">{{ session.loggedIn ? "收藏目录" : "第一步" }}</span>
      <strong class="text-xs">{{ session.loggedIn ? "还没有收藏夹目录" : "先扫码登录" }}</strong>
      <p class="text-[12px] text-foreground/72">{{ session.loggedIn ? "刷新后这里会出现你的收藏夹列表。" : "登录后自动拉取你的收藏夹。" }}</p>
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

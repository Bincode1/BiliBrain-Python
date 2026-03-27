<template>
  <aside class="sidebar">
    <div class="sidebar-top">
      <div class="identity-card compact-topbar">
        <div class="topbar-main">
          <div class="brand-block">
            <div class="brand-mark">档</div>
            <div class="brand-copy">
              <span class="brand-title">收藏夹</span>
              <span class="brand-caption">内容整理</span>
            </div>
          </div>
          <div class="account-meta compact-account">
            <span class="account-label">B 站账号</span>
            <span class="account-name">{{ session.loggedIn ? session.userName : "未登录" }}</span>
          </div>
        </div>
        <button class="switch-account compact-switch" type="button" @click="store.startQrLogin">
          {{ session.loggedIn ? "换账号" : "扫码登录" }}
        </button>
      </div>

      <div class="control-strip compact-controls">
        <div class="control-inline compact-inline">
          <span class="control-label-inline">时长</span>
          <label class="setting-mini compact-setting">
            <input v-model="processingSettings.max_video_minutes" type="number" min="1" max="300" />
          </label>
          <button class="ghost-button small" :disabled="processingSettings.saving" type="button" @click="store.saveSettings">
            保存
          </button>
        </div>
        <button class="ghost-button small danger-ghost subtle-reset" type="button" @click="store.resetAllProcessedContent">
          重置已加载
        </button>
      </div>
    </div>

    <div :class="statusClass(settingsStatus)">{{ settingsStatus.message }}</div>
    <div :class="statusClass(syncStatus)">{{ syncStatus.message }}</div>

    <section class="folders-section">
      <div class="folders-header">收藏夹目录</div>
      <div v-if="folders.length" class="folder-list folder-scroll">
        <article
          v-for="folder in folders"
          :key="folder.folder_id"
          class="folder-card"
          :class="{ active: selectedFolderId === String(folder.folder_id) }"
        >
          <button
            class="folder-toggle"
            :class="{ active: selectedFolderId === String(folder.folder_id) }"
            type="button"
            @click="store.openFolder(folder)"
          >
            <span>
              <strong>{{ folder.title }}</strong>
              <em>{{ folder.media_count }} 个视频 · 已入库 {{ folder.synced_videos || 0 }}</em>
            </span>
            <span class="folder-id">ID {{ folder.folder_id }}</span>
          </button>

          <div class="folder-ops">
            <button class="ghost-button" type="button" @click="store.openFolderSearch(folder)">搜 B 站</button>
            <button class="ghost-button" type="button" @click="store.syncFolder(folder)">同步元数据</button>
          </div>
        </article>
      </div>
      <div v-else class="workspace-empty-state">
        <span class="workspace-empty-kicker">{{ session.loggedIn ? "收藏目录" : "第一步" }}</span>
        <strong>{{ session.loggedIn ? "还没有收藏夹目录" : "先扫码登录" }}</strong>
        <p>{{ session.loggedIn ? "刷新后这里会出现你的收藏夹列表。" : "登录后自动拉取你的收藏夹。" }}</p>
        <div class="workspace-empty-actions">
          <button v-if="session.loggedIn" class="ghost-button" type="button" @click="store.loadFolders">刷新目录</button>
          <button v-else type="button" @click="store.startQrLogin">扫码登录</button>
        </div>
      </div>
    </section>
  </aside>
</template>

<script setup>
import { storeToRefs } from "pinia";

import { statusClass } from "@/composables/useStatus";
import { useWorkspaceStore } from "@/stores/workspace";

const store = useWorkspaceStore();
const { folders, processingSettings, selectedFolderId, session, settingsStatus, syncStatus } = storeToRefs(store);
</script>

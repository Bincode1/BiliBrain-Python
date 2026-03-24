<template>
  <aside class="sidebar">
    <div class="sidebar-top">
      <div class="identity-card compact-topbar">
        <div class="topbar-main">
          <div class="brand-block">
            <div class="brand-mark">B</div>
            <div class="brand-copy">
              <span class="brand-title">BiliBrain</span>
              <span class="brand-caption">私人技术档案库</span>
            </div>
          </div>
          <div class="account-meta compact-account">
            <span class="account-label">当前账号</span>
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
      <div class="folders-header">收藏夹</div>
      <div v-if="folders.length" class="folder-list folder-scroll">
        <article v-for="folder in folders" :key="folder.folder_id" class="folder-card">
          <button class="folder-toggle" type="button" @click="store.openFolder(folder)">
            <span>
              <strong>{{ folder.title }}</strong>
              <em>{{ folder.media_count }} 个视频 · 已入库 {{ folder.synced_videos || 0 }}</em>
            </span>
            <span class="folder-id">ID {{ folder.folder_id }}</span>
          </button>

          <div class="folder-ops">
            <button class="ghost-button" type="button" @click="store.syncFolder(folder)">同步元数据</button>
          </div>

          <div v-if="folder.expanded" class="video-stack">
            <div v-if="folder.loadingVideos" class="muted-box">正在读取视频列表...</div>
            <div v-else-if="folder.videoError" class="muted-box danger-text">{{ folder.videoError }}</div>
            <button
              v-for="video in folder.videos"
              :key="video.bvid"
              class="video-list-item"
              :class="[{ active: selectedVideoBvid === video.bvid && !video.is_invalid }, videoTone(video)]"
              type="button"
              :disabled="video.is_invalid"
              @click="store.selectVideo(folder, video)"
            >
              <div
                class="video-row-cover"
                :class="{ empty: !video.cover_url, clickable: !!video.watch_url }"
                @click.stop="openVideoLink(video)"
              >
                <img
                  v-if="video.cover_url && !video.coverLoadFailed"
                  :src="video.cover_url"
                  :alt="video.title"
                  loading="lazy"
                  referrerpolicy="no-referrer"
                  @error="video.coverLoadFailed = true"
                />
                <span v-else>{{ video.is_invalid ? "失效" : "封面" }}</span>
              </div>
              <div class="video-row-body">
                <div class="video-row-head">
                  <strong>{{ video.title }}</strong>
                  <div class="video-row-head-side">
                    <span class="state-dot">{{ video.is_invalid ? "已失效" : (video.sync_status || "pending") }}</span>
                    <span
                      v-if="video.watch_url"
                      class="video-link-chip"
                      @click.stop="openVideoLink(video)"
                    >
                      访问
                    </span>
                  </div>
                </div>
                <div class="video-row-meta">
                  <template v-if="video.is_invalid">
                    <span>该收藏内容已失效</span>
                    <span>无法处理或转写</span>
                  </template>
                  <template v-else>
                    <span>{{ formatDuration(video.duration) }}</span>
                    <span>{{ video.up_name || "未知 UP" }}</span>
                    <span>片段 {{ video.chunk_count || 0 }}</span>
                  </template>
                </div>
              </div>
            </button>
            <div v-if="!folder.loadingVideos && !folder.videoError && !folder.videos.length" class="muted-box">
              当前收藏夹还没有视频。
            </div>
          </div>
        </article>
      </div>
      <div v-else class="muted-box">
        {{ session.loggedIn ? "还没有收藏夹数据。" : "先扫码登录，页面会自动读取收藏夹。" }}
      </div>
    </section>
  </aside>
</template>

<script setup>
import { storeToRefs } from "pinia";

import { statusClass } from "@/composables/useStatus";
import { useWorkspaceStore } from "@/stores/workspace";
import { formatDuration, openVideoLink, videoTone } from "@/utils/video";

const store = useWorkspaceStore();
const { folders, processingSettings, selectedVideoBvid, session, settingsStatus, syncStatus } = storeToRefs(store);
</script>

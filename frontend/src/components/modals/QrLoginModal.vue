<template>
  <div v-if="qrModalOpen" class="modal-shell" @click.self="store.closeQrModal">
    <div class="modal-card">
      <div class="panel-head">
        <h2>扫码登录 Bilibili</h2>
        <p>扫描后会显示“等待验证”，验证完成后页面会自动刷新并重新加载收藏夹。</p>
      </div>
      <div class="qr-panel modal-qr" v-html="qrSvg || '正在生成二维码…'"></div>
      <div :class="statusClass(qrStatus)">{{ qrStatus.message }}</div>
      <div class="modal-actions">
        <button class="ghost-button" type="button" @click="store.closeQrModal">关闭</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { storeToRefs } from "pinia";

import { statusClass } from "@/composables/useStatus";
import { useWorkspaceStore } from "@/stores/workspace";

const store = useWorkspaceStore();
const { qrModalOpen, qrStatus, qrSvg } = storeToRefs(store);
</script>

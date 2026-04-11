<template>
  <Dialog :open="qrModalOpen" @update:open="(v) => { if (!v) store.closeQrModal() }">
    <DialogContent class="sm:max-w-sm">
      <DialogHeader>
        <DialogTitle>扫码登录 Bilibili</DialogTitle>
        <DialogDescription>
          扫描后会显示"等待验证"，验证完成后页面会自动刷新并重新加载收藏夹。
        </DialogDescription>
      </DialogHeader>

      <div class="flex justify-center py-4" v-html="qrSvg || '<span class=text-muted-foreground>正在生成二维码…</span>'" />

      <div v-if="qrStatus.show" :class="['text-sm text-center py-1', qrStatus.error ? 'text-destructive' : 'text-muted-foreground']">
        {{ qrStatus.message }}
      </div>

      <DialogFooter>
        <Button variant="ghost" @click="store.closeQrModal">关闭</Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>

<script setup>
import { storeToRefs } from "pinia";

import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";

import { useAuthStore } from "@/stores/auth";

const store = useAuthStore();
const { qrModalOpen, qrStatus, qrSvg } = storeToRefs(store);
</script>

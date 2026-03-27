<template>
  <aside class="app-sidebar-shell">
    <div class="app-sidebar-brand-panel">
      <div class="app-sidebar-brand">
        <div class="app-sidebar-brand-mark">B</div>
        <div class="app-sidebar-brand-copy">
          <span class="app-sidebar-brand-title">BiliBrain</span>
          <span class="app-sidebar-brand-caption">Personal AI</span>
        </div>
      </div>
    </div>

    <nav class="app-sidebar-nav" aria-label="全局导航">
      <AppSidebarItem v-for="item in navItems" :key="item.id" :item="item" />
    </nav>
  </aside>
</template>

<script setup>
import { computed } from "vue";
import { storeToRefs } from "pinia";

import AppSidebarItem from "@/components/navigation/AppSidebarItem.vue";
import { useAppShellStore } from "@/stores/appShell";

const store = useAppShellStore();
const { navSections } = storeToRefs(store);
const navItems = computed(() => navSections.value.flatMap((section) => section.items));
</script>

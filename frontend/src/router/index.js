import { createRouter, createWebHistory } from "vue-router";

import AppShell from "@/layouts/AppShell.vue";
import ChatFeatureView from "@/views/ChatFeatureView.vue";
import LibraryFeatureView from "@/views/LibraryFeatureView.vue";
import SkillsStoreView from "@/views/SkillsStoreView.vue";
import ToolsStoreView from "@/views/ToolsStoreView.vue";

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: "/",
      component: AppShell,
      children: [
        {
          path: "",
          redirect: { name: "chat" },
        },
        {
          path: "features/chat",
          name: "chat",
          component: ChatFeatureView,
          meta: { featureId: "chat" },
        },
        {
          path: "features/library",
          name: "library",
          component: LibraryFeatureView,
          meta: { featureId: "library" },
        },
        {
          path: "store/skills",
          name: "skills-store",
          component: SkillsStoreView,
          meta: { featureId: "skills-store" },
        },
        {
          path: "store/tools",
          name: "tools-store",
          component: ToolsStoreView,
          meta: { featureId: "tools-store" },
        },
        {
          path: "workspace",
          redirect: { name: "library" },
        },
      ],
    },
    {
      path: "/:pathMatch(.*)*",
      redirect: { name: "chat" },
    },
  ],
});

export default router;

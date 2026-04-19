<template>
  <Sidebar collapsible="icon">
    <SidebarHeader>
      <SidebarMenu>
        <SidebarMenuItem>
          <SidebarMenuButton size="lg" tooltip="BiliBrain">
            <div
              class="flex aspect-square size-7.5 items-center justify-center rounded-lg bg-primary text-primary-foreground text-[13px] font-bold"
            >
              B
            </div>
            <div class="flex flex-col gap-0.5 leading-none">
              <span class="text-[13px] font-semibold">BiliBrain</span>
              <span class="text-[12px] font-medium text-foreground/80">Personal AI</span>
            </div>
          </SidebarMenuButton>
        </SidebarMenuItem>
      </SidebarMenu>
    </SidebarHeader>

    <SidebarContent>
      <!-- Navigation groups -->
      <SidebarGroup v-for="section in navSections" :key="section.id">
        <SidebarGroupLabel>{{ section.title }}</SidebarGroupLabel>
        <SidebarGroupContent>
          <SidebarMenu>
            <SidebarMenuItem v-for="item in section.items" :key="item.id">
              <SidebarMenuButton
                as-child
                :tooltip="item.name"
                :is-active="isActive(item.routeName)"
              >
                <RouterLink :to="item.path">
                  <component :is="featureIcon(item.id)" />
                  <span>{{ item.name }}</span>
                </RouterLink>
              </SidebarMenuButton>
            </SidebarMenuItem>
          </SidebarMenu>
        </SidebarGroupContent>
      </SidebarGroup>

      <!-- Conversation list (chat page only) -->
      <SidebarGroup v-if="isOnChat">
        <SidebarGroupLabel class="flex items-center justify-between">
          <span>对话</span>
          <Button
            variant="ghost"
            size="sm"
            class="h-5 gap-1 px-1.5 text-[10px] group-data-[collapsible=icon]:hidden"
            @click="chatStore.createConversation"
          >
            <Plus class="size-3" />
            <span class="group-data-[collapsible=icon]:hidden">新会话</span>
          </Button>
        </SidebarGroupLabel>
        <SidebarGroupContent>
          <!-- Loading -->
          <div v-if="chatConversationsLoading" class="flex items-center justify-center py-4 text-[12px] font-medium text-foreground/72 group-data-[collapsible=icon]:hidden">
            加载中...
          </div>

          <!-- Empty -->
          <div v-else-if="!chatConversations.length" class="px-2 py-3 text-[12px] text-foreground/72 group-data-[collapsible=icon]:hidden">
            还没有会话
          </div>

          <!-- List -->
          <SidebarMenu v-else>
            <SidebarMenuItem
              v-for="(conversation, index) in chatConversations"
              :key="conversation.conversation_id"
            >
              <DropdownMenu>
                <DropdownMenuTrigger as-child>
                  <SidebarMenuButton
                    :is-active="Number(activeConversationId) === Number(conversation.conversation_id)"
                    :tooltip="conversationShortLabel(conversation, index)"
                    :disabled="chatConversationsLoading && Number(activeConversationId) === Number(conversation.conversation_id)"
                    @click="handleSelect(conversation.conversation_id)"
                  >
                    <MessageSquare class="size-4" />
                    <span class="truncate">{{ conversationShortLabel(conversation, index) }}</span>
                  </SidebarMenuButton>
                </DropdownMenuTrigger>
                <DropdownMenuContent side="right" align="start" class="w-28">
                  <DropdownMenuItem
                    :disabled="Number(renamingConversationId) === Number(conversation.conversation_id)"
                    @click="handleRename(conversation.conversation_id)"
                  >
                    重命名
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    class="text-destructive focus:text-destructive"
                    :disabled="Number(deletingConversationId) === Number(conversation.conversation_id)"
                    @click="handleDelete(conversation.conversation_id)"
                  >
                    删除
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </SidebarMenuItem>
          </SidebarMenu>
        </SidebarGroupContent>
      </SidebarGroup>
    </SidebarContent>

    <SidebarFooter>
      <SidebarMenu>
        <SidebarMenuItem>
          <SidebarMenuButton size="sm" @click="toggleSidebar">
            <PanelLeftClose v-if="isOpen" />
            <PanelLeft v-else />
            <span>{{ isOpen ? "收起" : "展开" }}</span>
          </SidebarMenuButton>
        </SidebarMenuItem>
      </SidebarMenu>
    </SidebarFooter>
  </Sidebar>
</template>

<script setup>
import { computed } from "vue";
import { storeToRefs } from "pinia";
import { useRoute, RouterLink } from "vue-router";
import {
  MessageSquare,
  FolderOpen,
  Sparkles,
  Wrench,
  PanelLeftClose,
  PanelLeft,
  Plus,
} from "lucide-vue-next";

import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from "@/components/ui/sidebar";
import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { useAppShellStore } from "@/stores/appShell";
import { useChatStore } from "@/stores/chat";
import { conversationShortLabel } from "@/utils/chat";

const store = useAppShellStore();
const { navSections } = storeToRefs(store);
const route = useRoute();
const { isOpen, toggleSidebar } = useSidebar();

const chatStore = useChatStore();
const { activeConversationId, chatConversations, chatConversationsLoading, deletingConversationId, renamingConversationId } = storeToRefs(chatStore);

const isOnChat = computed(() => route.name === "chat");

function isActive(routeName) {
  return route.name === routeName;
}

function featureIcon(id) {
  const map = {
    chat: MessageSquare,
    library: FolderOpen,
    "skills-store": Sparkles,
    "tools-store": Wrench,
  };
  return map[id] || MessageSquare;
}

async function handleRename(id) { await chatStore.renameConversation(id); }
async function handleDelete(id) { await chatStore.deleteConversation(id); }
async function handleSelect(id) { await chatStore.selectConversation(id); }
</script>

<template>
  <section class="flex h-full flex-col overflow-hidden border-l border-border p-3">
    <div class="flex items-center justify-between mb-2">
      <span class="text-xs font-medium text-muted-foreground">对话</span>
      <Button variant="ghost" size="sm" class="h-6 text-[11px]" @click="store.createConversation">
        新会话
      </Button>
    </div>

    <div class="flex flex-1 flex-col gap-1 overflow-y-auto">
      <!-- Loading -->
      <div v-if="chatConversationsLoading" class="flex items-center justify-center py-6 text-xs text-muted-foreground">
        正在读取会话...
      </div>

      <!-- Empty -->
      <div v-else-if="!chatConversations.length" class="flex flex-col items-center gap-2 rounded-xl border border-dashed border-border px-4 py-6 text-center">
        <strong class="text-xs">还没有会话</strong>
        <p class="text-[11px] text-muted-foreground">直接发送第一条消息就会自动创建。</p>
      </div>

      <!-- List -->
      <template v-else>
        <div
          v-for="(conversation, index) in chatConversations"
          :key="conversation.conversation_id"
          class="group relative flex items-center gap-1 rounded-xl px-2 py-1.5 transition-colors"
          :class="Number(activeConversationId) === Number(conversation.conversation_id) ? 'bg-secondary' : 'hover:bg-secondary/50'"
        >
          <button
            class="flex flex-1 flex-col gap-0.5 text-left"
            :disabled="chatConversationsLoading && Number(activeConversationId) === Number(conversation.conversation_id)"
            :title="conversationLabel(conversation, index)"
            @click="handleSelect(conversation.conversation_id)"
          >
            <span class="truncate text-xs font-medium">{{ conversationShortLabel(conversation, index) }}</span>
            <span class="text-[10px] text-muted-foreground">{{ conversation.message_count }} 条消息</span>
          </button>

          <DropdownMenu>
            <DropdownMenuTrigger as-child>
              <Button
                variant="ghost"
                size="sm"
                class="h-6 w-6 p-0 opacity-0 group-hover:opacity-100 transition-opacity"
                :disabled="
                  Number(deletingConversationId) === Number(conversation.conversation_id) ||
                  Number(renamingConversationId) === Number(conversation.conversation_id)
                "
              >
                ⋯
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" class="w-28">
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
        </div>
      </template>
    </div>
  </section>
</template>

<script setup>
import { storeToRefs } from "pinia";

import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";

import { useChatStore } from "@/stores/chat";
import { conversationLabel, conversationShortLabel } from "@/utils/chat";

const store = useChatStore();
const { activeConversationId, chatConversations, chatConversationsLoading, deletingConversationId, renamingConversationId } = storeToRefs(store);

async function handleRename(id) { await store.renameConversation(id); }
async function handleDelete(id) { await store.deleteConversation(id); }
async function handleSelect(id) { await store.selectConversation(id); }
</script>

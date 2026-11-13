<script setup lang="ts">
import { ref } from 'vue'

import MessageComposer from '@/components/chat/MessageComposer.vue'
import MessageList from '@/components/chat/MessageList.vue'
import AppHeader from '@/components/layout/AppHeader.vue'
import SessionSidebar from '@/components/layout/SessionSidebar.vue'
import type { ChatMessage } from '@/types/chat'

// P0 只验证壳与布局；消息来自 P2 的 SSE 流，这里保持空态
const messages = ref<ChatMessage[]>([])
</script>

<template>
  <div class="flex h-full">
    <session-sidebar />
    <div class="flex min-w-0 flex-1 flex-col">
      <app-header />
      <message-list :messages="messages" />
      <message-composer
        :disabled="true"
        hint="P0 基座已就绪：对话链路将在 P2 接入"
      />
    </div>
  </div>
</template>

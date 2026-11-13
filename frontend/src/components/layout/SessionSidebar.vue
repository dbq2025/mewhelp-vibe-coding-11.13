<script setup lang="ts">
import { storeToRefs } from 'pinia'

import { useSessionStore } from '@/stores/session'

const { sessions, currentId, isEmpty } = storeToRefs(useSessionStore())
</script>

<template>
  <aside class="flex w-64 shrink-0 flex-col border-r border-line bg-surface">
    <div class="flex h-14 items-center gap-2 border-b border-line px-4">
      <span class="grid h-7 w-7 place-items-center rounded-lg bg-brand text-xs font-bold text-brand-ink">
        EC
      </span>
      <span class="text-sm font-semibold">ecom-copilot</span>
    </div>

    <div class="p-3">
      <button
        type="button"
        class="w-full cursor-not-allowed rounded-lg border border-line bg-canvas px-3 py-2 text-xs text-muted"
        disabled
        title="会话创建将在 P2 接入"
      >
        + 新建会话
      </button>
    </div>

    <nav class="flex-1 overflow-y-auto px-2 pb-3">
      <p
        v-if="isEmpty"
        class="px-2 py-6 text-center text-xs leading-relaxed text-muted"
      >
        还没有会话记录<br>P2 起自动保存历史对话
      </p>
      <ul
        v-else
        class="space-y-1"
      >
        <li
          v-for="session in sessions"
          :key="session.id"
        >
          <button
            type="button"
            class="w-full truncate rounded-lg px-2 py-2 text-left text-xs"
            :class="session.id === currentId ? 'bg-brand-soft text-brand' : 'text-ink hover:bg-canvas'"
          >
            {{ session.title }}
          </button>
        </li>
      </ul>
    </nav>

    <div class="border-t border-line px-4 py-3 text-xs text-muted">
      未登录 · 游客模式
    </div>
  </aside>
</template>

<script setup lang="ts">
import { storeToRefs } from 'pinia'

import { useSessionStore } from '@/stores/session'

const emit = defineEmits<{
  create: []
  select: [id: string]
  remove: [id: string]
  logout: []
}>()

const sessionStore = useSessionStore()
const { sessions, currentId, isEmpty, loading } = storeToRefs(sessionStore)
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
        class="w-full rounded-lg border border-line bg-canvas px-3 py-2 text-xs text-ink hover:border-brand hover:text-brand"
        @click="emit('create')"
      >
        + 新建会话
      </button>
    </div>

    <nav class="flex-1 overflow-y-auto px-2 pb-3">
      <p
        v-if="loading && isEmpty"
        class="px-2 py-6 text-center text-xs text-muted"
      >
        加载中…
      </p>
      <p
        v-else-if="isEmpty"
        class="px-2 py-6 text-center text-xs leading-relaxed text-muted"
      >
        还没有会话记录<br>发第一条消息就会自动保存
      </p>
      <ul
        v-else
        class="space-y-1"
      >
        <li
          v-for="item in sessions"
          :key="item.id"
          class="group flex items-center gap-1"
        >
          <button
            type="button"
            class="min-w-0 flex-1 truncate rounded-lg px-2 py-2 text-left text-xs"
            :class="item.id === currentId ? 'bg-brand-soft text-brand' : 'text-ink hover:bg-canvas'"
            :title="item.title"
            @click="emit('select', item.id)"
          >
            {{ item.title }}
          </button>
          <button
            type="button"
            class="hidden shrink-0 rounded px-1 text-xs text-muted group-hover:block hover:text-danger"
            title="删除会话"
            aria-label="删除会话"
            @click="emit('remove', item.id)"
          >
            ×
          </button>
        </li>
      </ul>
    </nav>

    <div class="flex items-center justify-between border-t border-line px-4 py-3 text-xs text-muted">
      <span>已登录</span>
      <button
        type="button"
        class="hover:text-ink"
        @click="emit('logout')"
      >
        退出
      </button>
    </div>
  </aside>
</template>

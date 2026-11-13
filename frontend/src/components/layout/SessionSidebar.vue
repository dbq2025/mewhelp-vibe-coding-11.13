<script setup lang="ts">
import { storeToRefs } from 'pinia'

import SkeletonBlock from '@/components/common/SkeletonBlock.vue'
import { useSessionStore } from '@/stores/session'

withDefaults(defineProps<{ open?: boolean }>(), { open: false })

const emit = defineEmits<{
  create: []
  select: [id: string]
  remove: [id: string]
  logout: []
  close: []
}>()

const sessionStore = useSessionStore()
const { sessions, currentId, isEmpty, loading } = storeToRefs(sessionStore)
</script>

<template>
  <!-- 移动端：抽屉 + 遮罩；桌面端（md 以上）常驻左栏 -->
  <div
    v-if="open"
    class="fixed inset-0 z-30 bg-ink/30 md:hidden"
    aria-hidden="true"
    @click="emit('close')"
  />

  <aside
    class="fixed inset-y-0 left-0 z-40 flex w-72 shrink-0 flex-col border-r border-line bg-surface transition-transform duration-200 md:static md:z-auto md:w-64 md:translate-x-0"
    :class="open ? 'translate-x-0 shadow-xl md:shadow-none' : '-translate-x-full'"
    aria-label="会话列表"
  >
    <div class="flex h-14 items-center gap-2 border-b border-line px-4">
      <span class="grid h-7 w-7 place-items-center rounded-lg bg-brand text-xs font-bold text-brand-ink">
        EC
      </span>
      <span class="text-sm font-semibold">ecom-copilot</span>
      <button
        type="button"
        class="ml-auto rounded-md px-2 py-1 text-sm text-muted hover:text-ink md:hidden"
        aria-label="关闭会话列表"
        @click="emit('close')"
      >
        ×
      </button>
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
      <!-- 骨架屏：首屏加载时给出"有几条"的形状，比一行"加载中"更少跳动 -->
      <ul
        v-if="loading && isEmpty"
        class="space-y-2 px-1 py-1"
        aria-label="正在加载会话"
      >
        <li
          v-for="n in 6"
          :key="n"
          class="px-1 py-1.5"
        >
          <skeleton-block
            :w="n % 3 === 0 ? 'w-2/3' : 'w-full'"
            h="h-3.5"
          />
        </li>
      </ul>
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
          <!-- 触屏没有 hover，删除按钮在移动端常显；桌面端 hover 才出现 -->
          <button
            type="button"
            class="shrink-0 rounded px-1 text-xs text-muted hover:text-danger md:hidden md:group-hover:block"
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

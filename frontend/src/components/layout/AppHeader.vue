<script setup lang="ts">
import { onMounted } from 'vue'

import { useHealth } from '@/composables/useHealth'

const emit = defineEmits<{ toggleSidebar: [] }>()

const { label, tone, detail, check } = useHealth()

const DOT_CLASS: Record<'ok' | 'warn' | 'danger', string> = {
  ok: 'bg-ok',
  warn: 'bg-warn',
  danger: 'bg-danger',
}

onMounted(() => {
  void check()
})
</script>

<template>
  <header class="flex h-14 shrink-0 items-center justify-between gap-3 border-b border-line bg-surface px-3 sm:px-5">
    <div class="flex min-w-0 items-center gap-2">
      <button
        type="button"
        class="-ml-1 rounded-md px-2 py-1 text-muted hover:text-ink md:hidden"
        aria-label="打开会话列表"
        @click="emit('toggleSidebar')"
      >
        <svg
          width="18"
          height="18"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          stroke-linecap="round"
          aria-hidden="true"
        >
          <path d="M4 6h16M4 12h16M4 18h16" />
        </svg>
      </button>
      <h1 class="truncate text-sm font-semibold">
        智能客服
      </h1>
      <span class="hidden truncate text-xs text-muted sm:inline">商品咨询 · 订单进度 · 售后政策</span>
    </div>

    <div class="flex shrink-0 items-center gap-3">
      <span
        v-if="detail !== null"
        class="hidden text-xs text-muted lg:inline"
        :title="`api ${detail.version} · env ${detail.env}`"
      >
        db {{ detail.db }} · vector {{ detail.vectorVersion ?? detail.vector }}
      </span>
      <span
        class="inline-flex items-center gap-1.5 rounded-full border border-line px-2.5 py-1 text-xs text-muted"
        role="status"
        :aria-label="label"
      >
        <span
          class="h-1.5 w-1.5 rounded-full"
          :class="DOT_CLASS[tone]"
        />
        {{ label }}
      </span>
    </div>
  </header>
</template>

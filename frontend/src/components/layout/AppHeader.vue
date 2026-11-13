<script setup lang="ts">
import { onMounted } from 'vue'

import { useHealth } from '@/composables/useHealth'

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
  <header class="flex h-14 shrink-0 items-center justify-between border-b border-line bg-surface px-5">
    <div class="flex items-baseline gap-2">
      <h1 class="text-sm font-semibold">
        智能客服
      </h1>
      <span class="text-xs text-muted">商品咨询 · 订单进度 · 售后政策</span>
    </div>

    <div class="flex items-center gap-3">
      <span
        v-if="detail !== null"
        class="hidden text-xs text-muted sm:inline"
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

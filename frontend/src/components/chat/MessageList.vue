<script setup lang="ts">
import type { ChatMessage } from '@/types/chat'

defineProps<{ messages: ChatMessage[] }>()

const SUGGESTIONS = [
  '1000 块以内的降噪耳机有哪些',
  '帮我查下订单 20261101001 到哪了',
  '七天无理由是从签收算还是发货算',
]
</script>

<template>
  <div class="flex-1 overflow-y-auto px-5 py-8">
    <div
      v-if="messages.length === 0"
      class="mx-auto flex max-w-chat flex-col items-center gap-4 text-center"
    >
      <div class="grid h-12 w-12 place-items-center rounded-2xl bg-brand-soft text-lg font-bold text-brand">
        EC
      </div>
      <h2 class="text-lg font-semibold">
        有什么可以帮你？
      </h2>
      <p class="max-w-sm text-sm leading-relaxed text-muted">
        商品参数、价格库存、订单物流、退换货政策都可以直接问，回答里的事实都能溯源到数据库或知识库。
      </p>
      <ul class="mt-2 flex flex-wrap justify-center gap-2">
        <li
          v-for="item in SUGGESTIONS"
          :key="item"
        >
          <span class="inline-block rounded-full border border-line bg-surface px-3 py-1.5 text-xs text-muted">
            {{ item }}
          </span>
        </li>
      </ul>
    </div>

    <ul
      v-else
      class="mx-auto max-w-chat space-y-6"
    >
      <li
        v-for="message in messages"
        :key="message.id"
      >
        <p class="mb-1 text-xs font-medium text-muted">
          {{ message.role === 'user' ? '我' : '客服' }}
        </p>
        <p class="whitespace-pre-wrap text-sm leading-relaxed">
          {{ message.content }}
        </p>
      </li>
    </ul>
  </div>
</template>

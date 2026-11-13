<script setup lang="ts">
import { computed } from 'vue'

import type { ChatMessage } from '@/types/chat'

const props = defineProps<{ messages: ChatMessage[]; streaming: boolean }>()
const emit = defineEmits<{ retry: []; pick: [text: string] }>()

const SUGGESTIONS = [
  '1000 块以内的降噪耳机有哪些',
  '帮我查下订单 20261101001 到哪了',
  '七天无理由是从签收算还是发货算',
]

const INTENT_LABELS: Record<string, string> = {
  product_search: '商品检索',
  product_info: '商品详情',
  order_status: '订单物流',
  after_sales: '售后处理',
  policy_faq: '政策咨询',
  chitchat: '闲聊',
  handoff: '转人工',
  blocked: '已拦截',
}

/** 只有最后一轮还在生成时才显示过程提示，历史消息不显示 */
const lastIndex = computed(() => props.messages.length - 1)

function isLive(index: number, message: ChatMessage): boolean {
  return props.streaming && index === lastIndex.value && message.role === 'assistant'
}

function toolLabel(name: string): string {
  const labels: Record<string, string> = {
    search_products: '商品检索',
    get_product: '商品详情',
    compare_products: '参数对比',
    get_order: '订单查询',
    get_shipment: '物流查询',
    search_policy: '政策检索',
  }
  return labels[name] ?? name
}
</script>

<template>
  <div class="px-5 py-8">
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
          <button
            type="button"
            class="inline-block rounded-full border border-line bg-surface px-3 py-1.5 text-xs text-muted hover:border-brand hover:text-brand"
            @click="emit('pick', item)"
          >
            {{ item }}
          </button>
        </li>
      </ul>
    </div>

    <ul
      v-else
      class="mx-auto max-w-chat space-y-6"
    >
      <li
        v-for="(message, index) in messages"
        :key="message.id"
      >
        <div class="mb-1 flex items-center gap-2 text-xs text-muted">
          <span class="font-medium">{{ message.role === 'user' ? '我' : '客服' }}</span>
          <span
            v-if="message.role === 'assistant' && message.intent"
            class="rounded bg-canvas px-1.5 py-0.5 text-[11px]"
          >
            {{ INTENT_LABELS[message.intent] ?? message.intent }}
          </span>
          <span
            v-if="message.status === 'blocked'"
            class="rounded bg-danger/10 px-1.5 py-0.5 text-[11px] text-danger"
          >
            已拦截
          </span>
          <span
            v-else-if="message.status === 'incomplete' && !isLive(index, message)"
            class="rounded bg-warn/10 px-1.5 py-0.5 text-[11px] text-warn"
          >
            未完成
          </span>
          <span
            v-if="message.latencyMs !== undefined && message.status === 'ok'"
            class="text-[11px] text-muted/70"
          >
            {{ (message.latencyMs / 1000).toFixed(1) }}s
          </span>
        </div>

        <div class="whitespace-pre-wrap break-words text-sm leading-relaxed text-ink">
          {{ message.content }}<span
            v-if="isLive(index, message) && message.content === ''"
            class="text-muted"
          >…</span>
        </div>

        <!-- 工具过程：流式期间显示当前动作，结束后折叠成可展开的轨迹 -->
        <p
          v-if="isLive(index, message) && message.activity"
          class="mt-2 flex items-center gap-1.5 text-xs text-muted"
        >
          <span class="h-1.5 w-1.5 animate-pulse rounded-full bg-brand" />
          {{ message.activity.summary || '处理中…' }}
        </p>

        <details
          v-if="message.role === 'assistant' && (message.tools?.length ?? 0) > 0 && !isLive(index, message)"
          class="mt-2 text-xs text-muted"
        >
          <summary class="cursor-pointer select-none">
            查询过程（{{ message.tools?.length }} 步）
          </summary>
          <ul class="mt-1 space-y-1 border-l border-line pl-3">
            <li
              v-for="(tool, toolIndex) in message.tools"
              :key="`${tool.name}-${toolIndex}`"
              class="flex flex-wrap gap-2"
            >
              <span :class="tool.ok ? 'text-ok' : 'text-warn'">{{ tool.ok ? '✓' : '!' }}</span>
              <span>{{ toolLabel(tool.name) }}：{{ tool.summary }}</span>
              <span
                v-if="tool.latencyMs"
                class="text-muted/70"
              >{{ tool.latencyMs }}ms</span>
            </li>
          </ul>
        </details>

        <ul
          v-if="message.role === 'assistant' && (message.citations?.length ?? 0) > 0"
          class="mt-2 flex flex-wrap gap-1.5"
        >
          <li
            v-for="citation in message.citations"
            :key="citation.index"
          >
            <details>
              <summary
                class="cursor-pointer rounded border border-line bg-surface px-2 py-0.5 text-[11px] text-muted hover:border-brand hover:text-brand"
                :title="citation.snippet"
              >
                [{{ citation.index }}] {{ citation.title }}
              </summary>
              <p class="mt-1 max-w-md rounded bg-canvas p-2 text-[11px] leading-relaxed text-muted">
                {{ citation.snippet }}
              </p>
            </details>
          </li>
        </ul>

        <button
          v-if="index === lastIndex && message.role === 'assistant' && message.status === 'incomplete' && !streaming"
          type="button"
          class="mt-2 rounded border border-line px-2 py-1 text-xs text-muted hover:border-brand hover:text-brand"
          @click="emit('retry')"
        >
          重试本条
        </button>
      </li>
    </ul>
  </div>
</template>

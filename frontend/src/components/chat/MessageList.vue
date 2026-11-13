<script setup lang="ts">
import { computed } from 'vue'

import SkeletonBlock from '@/components/common/SkeletonBlock.vue'
import type { ChatMessage } from '@/types/chat'

const props = withDefaults(
  defineProps<{ messages: ChatMessage[]; streaming: boolean; loading?: boolean }>(),
  { loading: false },
)
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

/** 只有最后一轮的卡片可点，历史卡片只读——避免对已处理的动作重复提交 */
function actionable(index: number): boolean {
  return index === lastIndex.value && !props.streaming
}

function toolLabel(name: string): string {
  const labels: Record<string, string> = {
    search_products: '商品检索',
    get_product: '商品详情',
    compare_products: '参数对比',
    get_order: '订单查询',
    get_shipment: '物流查询',
    search_policy: '政策检索',
    create_after_sales: '提交售后',
  }
  return labels[name] ?? name
}
</script>

<template>
  <div class="px-4 py-6 sm:px-5 sm:py-8">
    <!-- 历史消息加载：用骨架屏占住"两个来回"的形状，避免空白闪一下再跳出来 -->
    <div
      v-if="loading"
      class="mx-auto max-w-chat space-y-7"
      aria-label="正在加载历史消息"
      aria-busy="true"
    >
      <div
        v-for="n in 2"
        :key="n"
        class="space-y-2"
      >
        <skeleton-block
          w="w-10"
          h="h-2.5"
        />
        <skeleton-block
          :w="n === 1 ? 'w-2/5' : 'w-4/5'"
          h="h-3.5"
        />
        <skeleton-block
          v-if="n === 2"
          w="w-3/5"
          h="h-3.5"
        />
      </div>
    </div>

    <div
      v-else-if="messages.length === 0"
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
        <div class="mb-1 flex flex-wrap items-center gap-2 text-xs text-muted">
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

        <!-- 流式期间正文末尾跟一个打字光标；光标是伪元素，不会被复制走 -->
        <div
          class="whitespace-pre-wrap break-words text-sm leading-relaxed text-ink"
          :class="{ caret: isLive(index, message) }"
        >
          {{ message.content }}
        </div>

        <!-- 待确认动作 / 写操作结果：售后与转人工都必须让用户看见"提交了什么" -->
        <div
          v-if="message.role === 'assistant' && message.action"
          class="mt-3 rounded-xl border px-3 py-2.5 text-xs"
          :class="{
            'border-brand/40 bg-brand-soft/40': message.action.kind === 'after_sales_confirm',
            'border-ok/30 bg-ok/5': message.action.kind === 'after_sales_done',
            'border-warn/30 bg-warn/5': message.action.kind === 'after_sales_rejected',
            'border-line bg-canvas': message.action.kind === 'handoff_ticket',
          }"
        >
          <template v-if="message.action.kind === 'after_sales_confirm'">
            <p class="mb-1 font-medium text-ink">
              待确认 · {{ message.action.typeLabel }}
            </p>
            <pre class="whitespace-pre-wrap font-sans text-[11px] leading-relaxed text-muted">{{ message.action.summary }}</pre>
            <div
              v-if="actionable(index)"
              class="mt-2 flex gap-2"
            >
              <button
                type="button"
                class="rounded-md bg-brand px-3 py-1.5 text-[11px] font-medium text-brand-ink hover:opacity-90"
                @click="emit('pick', message.action.confirmText)"
              >
                {{ message.action.confirmText }}
              </button>
              <button
                type="button"
                class="rounded-md border border-line px-3 py-1.5 text-[11px] text-muted hover:border-brand hover:text-brand"
                @click="emit('pick', message.action.cancelText)"
              >
                {{ message.action.cancelText }}
              </button>
            </div>
            <p
              v-else
              class="mt-1 text-[11px] text-muted/70"
            >
              历史记录，如需办理请重新发起
            </p>
          </template>

          <p
            v-else-if="message.action.kind === 'after_sales_done'"
            class="font-medium text-ok"
          >
            ✓ {{ message.action.created ? '工单已提交' : '已有工单在跟进' }}
            <span class="font-mono">{{ message.action.ticketNo }}</span>
            <span class="ml-1 font-normal text-muted">（{{ message.action.statusLabel }}）</span>
          </p>

          <p
            v-else-if="message.action.kind === 'after_sales_rejected'"
            class="font-medium text-warn"
          >
            无法受理 · {{ message.action.typeLabel }}
            <span class="mt-1 block font-normal text-muted">{{ message.action.message }}</span>
          </p>

          <p
            v-else-if="message.action.kind === 'handoff_ticket'"
            class="font-medium text-ink"
          >
            人工工单 <span class="font-mono">{{ message.action.ticketNo }}</span>
            <span class="ml-1 font-normal text-muted">（{{ message.action.statusLabel }}）</span>
          </p>
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

        <!-- 引用卡片：编号徽章 + 标题，点开看原文片段。编号与正文里的 [1][2] 对应 -->
        <ul
          v-if="message.role === 'assistant' && (message.citations?.length ?? 0) > 0"
          class="mt-2.5 flex flex-col gap-1.5"
        >
          <li
            v-for="citation in message.citations"
            :key="citation.index"
            class="max-w-md"
          >
            <details class="group rounded-lg border border-line bg-surface">
              <summary class="flex cursor-pointer select-none items-center gap-2 px-2.5 py-1.5 text-[11px] text-muted hover:text-ink">
                <span class="grid h-4 min-w-4 shrink-0 place-items-center rounded bg-brand-soft px-1 text-[10px] font-medium text-brand">
                  [{{ citation.index }}]
                </span>
                <span class="truncate">{{ citation.title }}</span>
                <span class="ml-auto shrink-0 text-[10px] text-muted/60 group-open:hidden">展开</span>
                <span class="ml-auto hidden shrink-0 text-[10px] text-muted/60 group-open:inline">收起</span>
              </summary>
              <p class="border-t border-line px-2.5 py-2 text-[11px] leading-relaxed text-muted">
                {{ citation.snippet }}
              </p>
            </details>
          </li>
        </ul>

        <button
          v-if="index === lastIndex && message.role === 'assistant' && message.status === 'incomplete' && !streaming"
          type="button"
          class="mt-2 rounded border border-line px-2.5 py-1 text-xs text-muted hover:border-brand hover:text-brand"
          @click="emit('retry')"
        >
          重试本条
        </button>
      </li>
    </ul>
  </div>
</template>

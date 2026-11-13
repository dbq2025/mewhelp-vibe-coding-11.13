<script setup lang="ts">
import { storeToRefs } from 'pinia'
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import MessageComposer from '@/components/chat/MessageComposer.vue'
import MessageList from '@/components/chat/MessageList.vue'
import AppHeader from '@/components/layout/AppHeader.vue'
import SessionSidebar from '@/components/layout/SessionSidebar.vue'
import { useChatStream } from '@/composables/useChatStream'
import { setToken } from '@/lib/api'
import { useChatStore } from '@/stores/chat'
import { useSessionStore } from '@/stores/session'

const route = useRoute()
const router = useRouter()
const sessionStore = useSessionStore()
const chatStore = useChatStore()
const { messages, streaming, error, notice, loading, canRetry } = storeToRefs(chatStore)
const { send, stop, retry, openSession } = useChatStream()

const composerText = ref('')
const scroller = ref<HTMLElement | null>(null)
/** 移动端侧栏默认关闭；桌面端由 CSS 常驻，这个状态只对 <md 生效 */
const sidebarOpen = ref(false)

/**
 * URL 里有会话 id 但消息还没到：此时既不是"空会话"也不该显示欢迎页。
 * 首屏是先拉会话列表、再拉消息，中间这段空窗如果不盖住，会先闪一下"有什么可以帮你"
 * 再跳成历史消息，看起来像是会话丢了。
 */
const historyLoading = computed(() => {
  const id = route.params.sessionId
  const hasRouteSession = typeof id === 'string' && id.length > 0
  return loading.value || (hasRouteSession && sessionStore.loading && messages.value.length === 0)
})

async function scrollToBottom(): Promise<void> {
  await nextTick()
  const element = scroller.value
  if (element !== null) element.scrollTop = element.scrollHeight
}

watch(() => messages.value.length, scrollToBottom)
watch(() => messages.value[messages.value.length - 1]?.content, scrollToBottom)

onMounted(async () => {
  await sessionStore.fetchSessions()
  const id = route.params.sessionId
  // 可选参数在 /chat 下可能是空串而不是 undefined，空串不能当成会话 id
  if (typeof id === 'string' && id.length > 0) {
    await openSession(id)
    await scrollToBottom()
  }
})

// 路由是会话的唯一入口：侧边栏点击、刷新、前进后退都走这里，避免两套切换逻辑
watch(
  () => route.params.sessionId,
  async (id, previous) => {
    if (typeof id !== 'string' || id.length === 0) return
    if (id === previous || id === sessionStore.currentId) return
    await openSession(id)
    await scrollToBottom()
  },
)

// 新建会话后把 URL 同步过去，刷新页面仍能回到这一刻的会话
watch(
  () => sessionStore.currentId,
  (id) => {
    if (id !== null && route.params.sessionId !== id) {
      void router.replace({ name: 'chat', params: { sessionId: id } })
    }
  },
)

// 抽屉打开时锁住背景滚动，否则移动端手指滑动会穿透到消息列表
watch(sidebarOpen, (open) => {
  document.body.style.overflow = open ? 'hidden' : ''
})

async function handleSend(): Promise<void> {
  const text = composerText.value.trim()
  if (!text || streaming.value) return
  composerText.value = ''
  await send(text)
  await scrollToBottom()
}

function handlePick(text: string): void {
  composerText.value = text
  void handleSend()
}

function closeSidebar(): void {
  sidebarOpen.value = false
}

async function handleCreate(): Promise<void> {
  stop()
  closeSidebar()
  chatStore.reset()
  const created = await sessionStore.createSession()
  await router.push({ name: 'chat', params: { sessionId: created.id } })
  await scrollToBottom()
}

async function handleSelect(id: string): Promise<void> {
  stop()
  closeSidebar()
  await router.push({ name: 'chat', params: { sessionId: id } })
}

async function handleRemove(id: string): Promise<void> {
  stop()
  await sessionStore.removeSession(id)
  const next = sessionStore.currentId
  if (next === null) {
    chatStore.reset()
    closeSidebar()
    await router.push({ name: 'chat', params: {} })
    return
  }
  await router.push({ name: 'chat', params: { sessionId: next } })
}

function handleLogout(): void {
  stop()
  setToken(null)
  sessionStore.clear()
  chatStore.reset()
  closeSidebar()
  void router.push({ name: 'login' })
}
</script>

<template>
  <div class="flex h-full overflow-hidden">
    <session-sidebar
      :open="sidebarOpen"
      @create="handleCreate"
      @select="handleSelect"
      @remove="handleRemove"
      @logout="handleLogout"
      @close="closeSidebar"
    />
    <div class="flex min-w-0 flex-1 flex-col">
      <app-header @toggle-sidebar="sidebarOpen = !sidebarOpen" />

      <p
        v-if="notice && notice.changed.length > 0"
        class="shrink-0 border-b border-line bg-brand-soft px-5 py-1.5 text-center text-xs text-brand"
      >
        已识别 {{ notice.changed.join('、') }}
      </p>

      <div
        ref="scroller"
        class="min-h-0 flex-1 overflow-y-auto"
      >
        <message-list
          :messages="messages"
          :streaming="streaming"
          :loading="historyLoading"
          @retry="retry"
          @pick="handlePick"
        />
      </div>

      <!-- 错误条：一句话说清 + 能立刻重试，不把用户堵在"再来一次"的空白里 -->
      <div
        v-if="error"
        class="flex shrink-0 flex-wrap items-center justify-center gap-x-3 gap-y-1 border-t border-line bg-danger/5 px-4 py-2 text-xs text-danger"
        role="alert"
      >
        <span class="text-center">{{ error }}</span>
        <button
          v-if="canRetry"
          type="button"
          class="rounded border border-danger/40 px-2 py-0.5 hover:bg-danger/10"
          @click="retry"
        >
          重试本条
        </button>
        <button
          type="button"
          class="text-danger/70 hover:text-danger"
          aria-label="关闭提示"
          @click="chatStore.clearError()"
        >
          忽略
        </button>
      </div>

      <message-composer
        v-model="composerText"
        :streaming="streaming"
        hint="回答中的事实来自商品库、订单库与政策知识库；查不到会直接告诉你"
        @send="handleSend"
        @stop="stop"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { storeToRefs } from 'pinia'
import { nextTick, onMounted, ref, watch } from 'vue'
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
const { messages, streaming, error, notice, loading } = storeToRefs(chatStore)
const { send, stop, retry, openSession } = useChatStream()

const composerText = ref('')
const scroller = ref<HTMLElement | null>(null)

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

async function handleCreate(): Promise<void> {
  stop()
  chatStore.reset()
  const created = await sessionStore.createSession()
  await router.push({ name: 'chat', params: { sessionId: created.id } })
  await scrollToBottom()
}

async function handleSelect(id: string): Promise<void> {
  stop()
  await router.push({ name: 'chat', params: { sessionId: id } })
}

async function handleRemove(id: string): Promise<void> {
  stop()
  await sessionStore.removeSession(id)
  const next = sessionStore.currentId
  if (next === null) {
    chatStore.reset()
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
  void router.push({ name: 'login' })
}
</script>

<template>
  <div class="flex h-full">
    <session-sidebar
      @create="handleCreate"
      @select="handleSelect"
      @remove="handleRemove"
      @logout="handleLogout"
    />
    <div class="flex min-w-0 flex-1 flex-col">
      <app-header />

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
        <p
          v-if="loading"
          class="px-5 py-8 text-center text-xs text-muted"
        >
          正在加载历史消息…
        </p>
        <message-list
          v-else
          :messages="messages"
          :streaming="streaming"
          @retry="retry"
          @pick="handlePick"
        />
      </div>

      <p
        v-if="error"
        class="shrink-0 border-t border-line bg-danger/5 px-5 py-1.5 text-center text-xs text-danger"
      >
        {{ error }}
      </p>

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

import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { api, ApiError } from '@/lib/api'
import type { SessionSummary } from '@/types/api'

/**
 * 会话列表状态（跨组件共享：侧边栏 + 聊天页都要用）。
 * 只放"选中哪个会话、有哪些会话"，消息本体在 chat store 里——避免一个 store 变成上帝对象。
 */
export const useSessionStore = defineStore('session', () => {
  const sessions = ref<SessionSummary[]>([])
  const currentId = ref<string | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)

  const isEmpty = computed(() => sessions.value.length === 0)
  const current = computed(
    () => sessions.value.find((item) => item.id === currentId.value) ?? null,
  )

  async function fetchSessions(): Promise<void> {
    loading.value = true
    error.value = null
    try {
      const data = await api.listSessions()
      sessions.value = data.items
    } catch (err) {
      error.value = err instanceof ApiError ? err.message : '会话列表加载失败'
    } finally {
      loading.value = false
    }
  }

  async function createSession(title?: string): Promise<SessionSummary> {
    const created = await api.createSession(title)
    sessions.value = [created, ...sessions.value]
    currentId.value = created.id
    return created
  }

  async function removeSession(id: string): Promise<void> {
    await api.deleteSession(id)
    sessions.value = sessions.value.filter((item) => item.id !== id)
    if (currentId.value === id) {
      currentId.value = sessions.value[0]?.id ?? null
    }
  }

  async function renameSession(id: string, title: string): Promise<void> {
    const updated = await api.renameSession(id, title)
    sessions.value = sessions.value.map((item) => (item.id === id ? updated : item))
  }

  function selectSession(id: string): void {
    currentId.value = id
  }

  /** 首条消息后服务端会按首句改名，这里同步一下侧边栏标题 */
  function syncTitle(id: string, title: string): void {
    sessions.value = sessions.value.map((item) => (item.id === id ? { ...item, title } : item))
  }

  function clear(): void {
    sessions.value = []
    currentId.value = null
  }

  return {
    sessions,
    currentId,
    current,
    loading,
    error,
    isEmpty,
    fetchSessions,
    createSession,
    removeSession,
    renameSession,
    selectSession,
    syncTitle,
    clear,
  }
})

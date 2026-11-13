import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

export interface SessionSummary {
  id: string
  title: string
  updatedAt: string
}

/**
 * 会话级状态（跨组件共享）：当前会话、会话列表。
 * 服务端列表数据在 P2 接入接口后填充，这里不做任何 HTTP 调用。
 */
export const useSessionStore = defineStore('session', () => {
  const sessions = ref<SessionSummary[]>([])
  const currentId = ref<string | null>(null)

  const isEmpty = computed(() => sessions.value.length === 0)

  function selectSession(id: string): void {
    currentId.value = id
  }

  return { sessions, currentId, isEmpty, selectSession }
})

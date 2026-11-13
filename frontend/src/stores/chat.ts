import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { api, ApiError } from '@/lib/api'
import type { ChatMessage, Citation, MessageAction, SlotNotice, ToolTrace } from '@/types/chat'
import type { MessageDto } from '@/types/api'

/**
 * 消息状态机（单一真源）。
 * 只处理"事件 → 消息列表"的纯逻辑，不碰 fetch/AbortController（那在 composable 里），
 * 这样 SSE 事件序列可以被单测直接喂进来，不需要起服务。
 */
export const useChatStore = defineStore('chat', () => {
  const messages = ref<ChatMessage[]>([])
  const streaming = ref(false)
  const loading = ref(false)
  const error = ref<string | null>(null)
  const notice = ref<SlotNotice | null>(null)

  const lastAssistant = computed(() =>
    [...messages.value].reverse().find((item) => item.role === 'assistant'),
  )
  const canRetry = computed(
    () => !streaming.value && lastAssistant.value?.status === 'incomplete',
  )

  function fromDto(dto: MessageDto): ChatMessage {
    return {
      id: String(dto.id),
      role: dto.role,
      content: dto.content,
      status: (dto.status as ChatMessage['status']) ?? 'ok',
      intent: dto.intent ?? undefined,
      citations: (dto.citations as Citation[]) ?? [],
      tools: (dto.tools as ToolTrace[]) ?? [],
      latencyMs: dto.latencyMs ?? undefined,
      createdAt: dto.createdAt,
    }
  }

  async function loadMessages(sessionId: string): Promise<void> {
    loading.value = true
    error.value = null
    notice.value = null
    try {
      const data = await api.listMessages(sessionId)
      messages.value = data.items.map(fromDto)
    } catch (err) {
      error.value = err instanceof ApiError ? err.message : '历史消息加载失败'
      messages.value = []
    } finally {
      loading.value = false
    }
  }

  function reset(): void {
    messages.value = []
    streaming.value = false
    error.value = null
    notice.value = null
  }

  function pushUser(text: string): void {
    messages.value.push({
      id: `local-user-${Date.now()}`,
      role: 'user',
      content: text,
      status: 'ok',
    })
  }

  function beginAssistant(): void {
    messages.value.push({
      id: `local-assistant-${Date.now()}`,
      role: 'assistant',
      content: '',
      status: 'incomplete',
      pending: true,
      citations: [],
      tools: [],
      activity: null,
    })
    streaming.value = true
    error.value = null
  }

  function currentAssistant(): ChatMessage | null {
    const last = messages.value[messages.value.length - 1]
    return last !== undefined && last.role === 'assistant' ? last : null
  }

  function applyEvent(event: string, data: Record<string, unknown>): void {
    const target = currentAssistant()

    switch (event) {
      case 'meta': {
        if (target === null) return
        if (typeof data.messageId === 'number') target.id = String(data.messageId)
        target.intent = typeof data.intent === 'string' ? data.intent : undefined
        target.pending = false
        return
      }
      case 'slots': {
        const payload = data.slots as SlotNotice | undefined
        if (payload && Array.isArray(payload.changed) && payload.changed.length > 0) {
          notice.value = payload
        }
        return
      }
      case 'tool': {
        if (target === null) return
        const name = String(data.name ?? '')
        const status = data.status === 'start' ? 'start' : 'end'
        const summary = String(data.summary ?? '')
        target.activity = { name, status, summary }
        if (status === 'end') {
          target.tools = [
            ...(target.tools ?? []),
            {
              name,
              ok: data.ok !== false,
              summary,
              latencyMs: typeof data.latencyMs === 'number' ? data.latencyMs : undefined,
            },
          ]
        }
        return
      }
      case 'delta': {
        if (target === null) return
        target.content += String(data.text ?? '')
        return
      }
      case 'citation': {
        if (target === null) return
        const citation = data as unknown as Citation
        if (citation.index !== undefined) {
          target.citations = [...(target.citations ?? []), citation]
        }
        return
      }
      case 'action': {
        if (target === null) return
        const action = data.action as MessageAction | undefined
        if (action?.kind) target.action = action
        return
      }
      case 'error': {
        error.value = String(data.message ?? '生成失败')
        return
      }
      case 'done': {
        if (target === null) return
        target.status = (data.status as ChatMessage['status']) ?? 'ok'
        target.pending = false
        target.activity = null
        if (typeof data.latencyMs === 'number') target.latencyMs = data.latencyMs
        streaming.value = false
        return
      }
      default:
        return
    }
  }

  /** 流中断/异常：把最后一条标成 incomplete，前端显示"重试本条" */
  function markInterrupted(reason: string): void {
    streaming.value = false
    error.value = reason
    const target = currentAssistant()
    if (target !== null) {
      target.status = 'incomplete'
      target.activity = null
      target.pending = false
    }
  }

  function dropLastAssistant(): void {
    const last = messages.value[messages.value.length - 1]
    if (last?.role === 'assistant') {
      messages.value.pop()
    }
  }

  return {
    messages,
    streaming,
    loading,
    error,
    notice,
    lastAssistant,
    canRetry,
    loadMessages,
    reset,
    pushUser,
    beginAssistant,
    applyEvent,
    markInterrupted,
    dropLastAssistant,
  }
})

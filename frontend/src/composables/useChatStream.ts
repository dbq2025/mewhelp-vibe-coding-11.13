/**
 * 流式对话的运输层：AbortController、SSE 读取、生命周期清理。
 *
 * 状态本身放在 `stores/chat.ts`（纯函数式、可单测），这里只做副作用与清理。
 * **必须在 onScopeDispose 里 abort**：否则切会话/离开页面时旧流还在写消息列表，
 * 会出现"A 会话的流串进 B 会话"这种难查的串台（agent.md §4）。
 */

import { onScopeDispose, ref } from 'vue'

import { streamChat } from '@/lib/api'
import { ApiError } from '@/lib/api'
import { readSse } from '@/lib/sse'
import { useChatStore } from '@/stores/chat'
import { useSessionStore } from '@/stores/session'

function newClientMsgId(): string {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
}

export function useChatStream() {
  const sessionStore = useSessionStore()
  const chatStore = useChatStore()
  const controller = ref<AbortController | null>(null)

  async function openSession(sessionId: string): Promise<void> {
    stop()
    sessionStore.selectSession(sessionId)
    chatStore.reset()
    await chatStore.loadMessages(sessionId)
  }

  async function ensureSession(): Promise<string> {
    if (sessionStore.currentId !== null) return sessionStore.currentId
    const created = await sessionStore.createSession()
    chatStore.reset()
    return created.id
  }

  async function send(text: string): Promise<void> {
    const content = text.trim()
    if (!content || chatStore.streaming) return

    let sessionId: string
    try {
      sessionId = await ensureSession()
    } catch (err) {
      chatStore.markInterrupted(err instanceof ApiError ? err.message : '会话创建失败')
      return
    }

    chatStore.pushUser(content)
    chatStore.beginAssistant()
    const abort = new AbortController()
    controller.value = abort

    try {
      const response = await streamChat(
        { sessionId, message: content, clientMsgId: newClientMsgId() },
        abort.signal,
      )
      for await (const event of readSse(response, abort.signal)) {
        chatStore.applyEvent(event.event, event.data)
        if (event.event === 'done') break
      }
      if (!abort.signal.aborted && chatStore.streaming) {
        // 服务端没发 done 就断流了（网络中断/网关超时）
        chatStore.markInterrupted('连接中断，可重试本条')
      }
      // 首条消息后标题由服务端生成，本地先按首句同步，避免侧边栏一直显示"新会话"
      if (sessionStore.current?.title === '新会话') {
        sessionStore.syncTitle(sessionId, content.slice(0, 30))
      }
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') {
        chatStore.markInterrupted('已停止生成')
      } else {
        chatStore.markInterrupted(err instanceof ApiError ? err.message : '网络异常，可重试本条')
      }
    } finally {
      controller.value = null
      if (chatStore.streaming) chatStore.markInterrupted('已停止生成')
    }
  }

  function stop(): void {
    controller.value?.abort()
    controller.value = null
    if (chatStore.streaming) chatStore.markInterrupted('已停止生成')
  }

  /** 重试最后一条提问：去掉失败的助手气泡，把同一个问题再发一次。 */
  async function retry(): Promise<void> {
    if (chatStore.streaming) return
    const lastUser = [...chatStore.messages].reverse().find((item) => item.role === 'user')
    if (lastUser === undefined) return
    chatStore.dropLastAssistant()
    const text = lastUser.content
    // 本地去掉重复的用户气泡，重新走一次 send（服务端会作为新一轮落库）
    chatStore.messages.pop()
    await send(text)
  }

  onScopeDispose(() => {
    stop()
  })

  return { send, stop, retry, openSession, ensureSession }
}

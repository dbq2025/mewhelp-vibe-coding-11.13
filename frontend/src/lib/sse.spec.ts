import { describe, expect, it } from 'vitest'

import { parseSseChunk, SseParseError } from '@/lib/sse'
import { useChatStore } from '@/stores/chat'
import { createPinia, setActivePinia } from 'pinia'

describe('parseSseChunk', () => {
  it('解析事件名与 JSON 数据', () => {
    const raw = 'event: meta\ndata: {"intent":"product_search"}\n\nevent: delta\ndata: {"text":"你"}\n\n'
    const events = parseSseChunk(raw)
    expect(events).toHaveLength(2)
    expect(events[0]).toEqual({ event: 'meta', data: { intent: 'product_search' } })
    expect(events[1].event).toBe('delta')
  })

  it('忽略注释行与空块', () => {
    expect(parseSseChunk(': keep-alive\n\n\n')).toEqual([])
  })

  it('JSON 非法时抛 SseParseError，不静默吞掉', () => {
    expect(() => parseSseChunk('event: delta\ndata: {oops}\n\n')).toThrow(SseParseError)
  })
})

describe('chat store 事件状态机', () => {
  it('按 meta/tool/delta/citation/done 组装一条助手消息', () => {
    setActivePinia(createPinia())
    const store = useChatStore()
    store.pushUser('1000以内的降噪耳机')
    store.beginAssistant()

    store.applyEvent('meta', { messageId: 7, intent: 'product_search', confidence: 0.9 })
    store.applyEvent('tool', { name: 'search_products', status: 'start', summary: '正在筛选商品…' })
    store.applyEvent('tool', {
      name: 'search_products',
      status: 'end',
      summary: '找到 3 件商品',
      ok: true,
      latencyMs: 12,
    })
    store.applyEvent('delta', { text: '有 3 款可选，' })
    store.applyEvent('delta', { text: '459 元起。' })
    store.applyEvent('citation', { index: 1, title: '运费规则', docId: 3, snippet: '满 99 免运费' })
    store.applyEvent('done', { messageId: 7, latencyMs: 1500, status: 'ok' })

    const assistant = store.messages[1]
    expect(assistant.id).toBe('7')
    expect(assistant.content).toBe('有 3 款可选，459 元起。')
    expect(assistant.tools?.[0].summary).toBe('找到 3 件商品')
    expect(assistant.citations?.[0].title).toBe('运费规则')
    expect(assistant.status).toBe('ok')
    expect(store.streaming).toBe(false)
  })

  it('中断后标记 incomplete 并允许重试', () => {
    setActivePinia(createPinia())
    const store = useChatStore()
    store.pushUser('查订单')
    store.beginAssistant()
    store.applyEvent('delta', { text: '正在查询' })
    store.markInterrupted('已停止生成')

    expect(store.messages[1].status).toBe('incomplete')
    expect(store.canRetry).toBe(true)
    expect(store.error).toBe('已停止生成')
  })
})

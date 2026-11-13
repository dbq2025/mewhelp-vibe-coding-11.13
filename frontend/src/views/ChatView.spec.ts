import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import ChatView from '@/views/ChatView.vue'

const HEALTH_OK = {
  code: 0,
  message: 'ok',
  data: {
    status: 'ok',
    db: 'ok',
    vector: 'ok',
    vectorVersion: '0.8.7',
    version: '0.1.0',
    env: 'test',
  },
  traceId: 'test-trace',
}

const SESSIONS = {
  code: 0,
  message: 'ok',
  data: {
    items: [{ id: '11111111-1111-1111-1111-111111111111', title: '降噪耳机推荐', createdAt: '', updatedAt: '' }],
    page: { nextCursor: null, hasMore: false, total: null },
  },
  traceId: 'test-trace',
}

const MESSAGES = {
  code: 0,
  message: 'ok',
  data: {
    items: [
      { id: 1, role: 'user', content: '1000以内的降噪耳机', status: 'ok', intent: null, citations: [], tools: [], latencyMs: null, createdAt: '' },
      {
        id: 2,
        role: 'assistant',
        content: '有 3 款可选，最便宜的是云雀 Quiet 2，459 元。',
        status: 'ok',
        intent: 'product_search',
        citations: [{ index: 1, docId: 3, title: '运费规则', snippet: '满 99 免运费' }],
        tools: [{ name: 'search_products', ok: true, summary: '找到 3 件商品', latencyMs: 12 }],
        latencyMs: 1800,
        createdAt: '',
      },
    ],
    page: { nextCursor: null, hasMore: false, total: null },
  },
  traceId: 'test-trace',
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function mockApi(): void {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.startsWith('/health')) return jsonResponse(HEALTH_OK)
      if (url.includes('/messages')) return jsonResponse(MESSAGES)
      if (url.startsWith('/api/v1/sessions')) return jsonResponse(SESSIONS)
      return jsonResponse({ code: 0, message: 'ok', data: null, traceId: 't' })
    }),
  )
}

async function mountView(path = '/chat') {
  const router = makeRouter(path)
  // 路由未就绪时 route.params 还是空的，挂载会拿不到 sessionId
  await router.isReady()
  const wrapper = mount(ChatView, { global: { plugins: [createPinia(), router] } })
  await flushPromises()
  return wrapper
}

function makeRouter(path = '/chat') {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/chat/:sessionId?', name: 'chat', component: ChatView },
      { path: '/login', name: 'login', component: { template: '<div>login</div>' } },
    ],
  })
  void router.push(path)
  return router
}

describe('ChatView', () => {
  beforeEach(() => {
    mockApi()
  })

  it('渲染骨架、空态引导与可用输入框', async () => {
    const wrapper = await mountView('/chat')

    expect(wrapper.text()).toContain('ecom-copilot')
    expect(wrapper.text()).toContain('有什么可以帮你')
    expect(wrapper.text()).toContain('七天无理由是从签收算还是发货算')
    expect(wrapper.find('textarea').attributes('disabled')).toBeUndefined()
  })

  it('健康检查成功后显示服务正常', async () => {
    const wrapper = await mountView('/chat')

    expect(wrapper.text()).toContain('服务正常')
  })

  it('会话列表出现在侧边栏', async () => {
    const wrapper = await mountView('/chat')

    expect(wrapper.text()).toContain('降噪耳机推荐')
    expect(wrapper.text()).toContain('+ 新建会话')
  })

  it('打开会话后渲染历史消息、工具轨迹与引用', async () => {
    const wrapper = await mountView('/chat/11111111-1111-1111-1111-111111111111')

    expect(wrapper.text()).toContain('1000以内的降噪耳机')
    expect(wrapper.text()).toContain('云雀 Quiet 2')
    expect(wrapper.text()).toContain('查询过程（1 步）')
    expect(wrapper.text()).toContain('[1] 运费规则')
  })

  it('健康检查失败时降级为服务不可用且不抛错', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input)
        if (url.startsWith('/health')) throw new TypeError('failed to fetch')
        if (url.startsWith('/api/v1/sessions')) return jsonResponse(SESSIONS)
        return jsonResponse({ code: 0, message: 'ok', data: null, traceId: 't' })
      }),
    )
    const wrapper = await mountView('/chat')

    expect(wrapper.text()).toContain('服务不可用')
  })
})

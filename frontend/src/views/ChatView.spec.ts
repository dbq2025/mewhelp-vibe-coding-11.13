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

function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/', component: ChatView }],
  })
}

describe('ChatView 壳页', () => {
  beforeEach(() => {
    vi.stubGlobal(
      'fetch',
      vi.fn(
        async () =>
          new Response(JSON.stringify(HEALTH_OK), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          }),
      ),
    )
  })

  it('渲染三栏骨架与空态引导', () => {
    const wrapper = mount(ChatView, {
      global: { plugins: [createPinia(), makeRouter()] },
    })

    expect(wrapper.text()).toContain('ecom-copilot')
    expect(wrapper.text()).toContain('有什么可以帮你')
    expect(wrapper.text()).toContain('七天无理由是从签收算还是发货算')
    expect(wrapper.find('textarea').attributes('disabled')).toBeDefined()
  })

  it('健康检查成功后显示服务正常', async () => {
    const wrapper = mount(ChatView, {
      global: { plugins: [createPinia(), makeRouter()] },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('服务正常')
    expect(vi.mocked(fetch)).toHaveBeenCalledWith('/health', expect.anything())
  })

  it('健康检查失败时降级为服务不可用且不抛错', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new TypeError('failed to fetch')
      }),
    )
    const wrapper = mount(ChatView, {
      global: { plugins: [createPinia(), makeRouter()] },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('服务不可用')
  })
})

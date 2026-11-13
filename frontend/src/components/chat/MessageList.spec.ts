import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import MessageList from '@/components/chat/MessageList.vue'
import type { ChatMessage } from '@/types/chat'

/**
 * 售后确认卡片是**写操作入口**：按钮文案、点击回传的文本都要对。
 * 点错一次就是一张真实工单，所以这里断言到按钮文本与事件载荷。
 */
describe('MessageList 售后动作卡片', () => {
  it('渲染待确认摘要与两个按钮，点击回传确认文案', async () => {
    const message: ChatMessage = {
      id: '1',
      role: 'assistant',
      content: '我核对到这笔订单…',
      status: 'ok',
      action: {
        kind: 'after_sales_confirm',
        orderNo: '20261101008',
        type: 'return',
        typeLabel: '退货退款',
        summary: '· 订单号：20261101008（已发货）',
        confirmText: '确认提交',
        cancelText: '先不申请',
      },
    }
    const wrapper = mount(MessageList, { props: { messages: [message], streaming: false } })

    expect(wrapper.text()).toContain('待确认 · 退货退款')
    expect(wrapper.text()).toContain('20261101008')

    const buttons = wrapper.findAll('button')
    const confirm = buttons.find((button) => button.text() === '确认提交')
    const cancel = buttons.find((button) => button.text() === '先不申请')
    expect(confirm).toBeTruthy()
    expect(cancel).toBeTruthy()

    await confirm?.trigger('click')
    await cancel?.trigger('click')
    const picked = wrapper.emitted('pick')
    expect(picked).toEqual([['确认提交'], ['先不申请']])
  })

  it('历史卡片不可点击（避免重复提交）', () => {
    const message: ChatMessage = {
      id: '1',
      role: 'assistant',
      content: '…',
      status: 'ok',
      action: {
        kind: 'after_sales_confirm',
        orderNo: '20261101008',
        type: 'return',
        typeLabel: '退货退款',
        summary: '…',
        confirmText: '确认提交',
        cancelText: '先不申请',
      },
    }
    const later: ChatMessage = { id: '2', role: 'user', content: '谢谢', status: 'ok' }
    const wrapper = mount(MessageList, { props: { messages: [message, later], streaming: false } })
    expect(wrapper.text()).toContain('待确认')
    expect(wrapper.findAll('button')).toHaveLength(0)
  })

  it('建单结果展示工单号', () => {
    const message: ChatMessage = {
      id: '1',
      role: 'assistant',
      content: '已提交',
      status: 'ok',
      action: {
        kind: 'after_sales_done',
        ticketNo: 'AS202611130004',
        orderNo: '20261101008',
        type: 'return',
        typeLabel: '退货退款',
        status: 'pending',
        statusLabel: '待受理',
        created: true,
      },
    }
    const wrapper = mount(MessageList, { props: { messages: [message], streaming: false } })
    expect(wrapper.text()).toContain('工单已提交')
    expect(wrapper.text()).toContain('AS202611130004')
    expect(wrapper.text()).toContain('待受理')
  })
})

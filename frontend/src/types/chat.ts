export type MessageRole = 'user' | 'assistant'

export type MessageStatus = 'ok' | 'incomplete' | 'blocked'

export interface Citation {
  index: number
  title: string
  docId: number
  snippet: string
}

/** 落库后的工具轨迹（messages.tools 直接渲染） */
export interface ToolTrace {
  name: string
  ok: boolean
  summary: string
  errorCode?: string | null
  latencyMs?: number
}

/** 流式阶段的工具状态（start/end 两条），渲染成"正在查询订单…"这类提示 */
export interface ToolActivity {
  name: string
  status: 'start' | 'end'
  summary: string
}

/**
 * 服务端推来的"待办/结果卡片"（SSE `action` 事件）。
 * 售后与转人工是**写操作**，前端必须让用户看到"要提交什么"再点确认，
 * 而不是靠一句模型生成的"已为你提交"。
 */
export type MessageAction =
  | {
      kind: 'after_sales_confirm'
      orderNo: string
      type: string
      typeLabel: string
      reason?: string
      summary: string
      confirmText: string
      cancelText: string
    }
  | {
      kind: 'after_sales_done'
      ticketNo: string
      orderNo: string
      type: string
      typeLabel: string
      status: string
      statusLabel: string
      created: boolean
    }
  | {
      kind: 'after_sales_rejected'
      orderNo: string
      type: string
      typeLabel: string
      message: string
    }
  | {
      kind: 'handoff_ticket'
      ticketNo: string
      status: string
      statusLabel: string
      created: boolean
    }

export interface ChatMessage {
  id: string
  role: MessageRole
  content: string
  status: MessageStatus
  intent?: string
  citations?: Citation[]
  tools?: ToolTrace[]
  activity?: ToolActivity | null
  /** 待确认动作或建单结果，由 SSE `action` 事件填充；刷新后从文本还原，不强求存在 */
  action?: MessageAction | null
  latencyMs?: number
  /** 还没拿到服务端 messageId 时的占位标记 */
  pending?: boolean
  createdAt?: string
}

/** 槽位变更提示，例如「已识别 价格上限 ¥1000」 */
export interface SlotNotice {
  changed: string[]
  values: Record<string, string | number>
}

export interface Usage {
  prompt: number
  completion: number
}

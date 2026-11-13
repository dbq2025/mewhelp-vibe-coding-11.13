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

export interface ChatMessage {
  id: string
  role: MessageRole
  content: string
  status: MessageStatus
  intent?: string
  citations?: Citation[]
  tools?: ToolTrace[]
  activity?: ToolActivity | null
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

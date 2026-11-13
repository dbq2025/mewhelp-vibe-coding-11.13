export type MessageRole = 'user' | 'assistant' | 'system'

export type MessageStatus = 'ok' | 'incomplete' | 'blocked'

export interface Citation {
  index: number
  title: string
  docId: string
  snippet: string
}

export interface ToolTrace {
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
  createdAt: string
}

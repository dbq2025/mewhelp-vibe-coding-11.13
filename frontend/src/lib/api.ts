/**
 * 唯一网络出口（agent.md §4）：组件禁止直接 fetch。
 * 职责：拼 baseURL、带 token、解 envelope、统一抛 ApiError。
 */

import type {
  ApiResponse,
  HealthData,
  MessageDto,
  MetaData,
  PageMeta,
  SessionSummary,
  TokenData,
} from '@/types/api'

const TOKEN_KEY = 'ecom-copilot.token'

export class ApiError extends Error {
  readonly code: number
  readonly httpStatus: number

  constructor(code: number, message: string, httpStatus: number) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.httpStatus = httpStatus
  }
}

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token: string | null): void {
  if (token === null) {
    localStorage.removeItem(TOKEN_KEY)
    return
  }
  localStorage.setItem(TOKEN_KEY, token)
}

/**
 * 429 单独处理：后端的文案是通用兜底，而 `Retry-After` 才是"还要等几秒"的准确答案。
 * 把秒数拼进提示，用户不用猜"稍后"是多久（P4 验收第 4 条）。
 */
function rateLimitMessage(response: Response, fallback: string): string {
  const raw = response.headers.get('Retry-After')
  const seconds = raw === null ? NaN : Number(raw)
  if (Number.isFinite(seconds) && seconds > 0) {
    return `请求太频繁了，${Math.ceil(seconds)} 秒后再试一次`
  }
  return fallback
}

async function request<T>(url: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  headers.set('Accept', 'application/json')
  if (init.body !== undefined) {
    headers.set('Content-Type', 'application/json')
  }
  const token = getToken()
  if (token !== null) {
    headers.set('Authorization', `Bearer ${token}`)
  }

  let response: Response
  try {
    response = await fetch(url, { ...init, headers })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw error
    }
    throw new ApiError(-1, '网络连接失败，请检查后端服务是否启动', 0)
  }

  const body = (await response.json().catch(() => null)) as ApiResponse<T> | null
  if (body === null) {
    throw new ApiError(-1, `响应不是合法 JSON（HTTP ${response.status}）`, response.status)
  }
  if (body.code !== 0) {
    const message =
      response.status === 429 ? rateLimitMessage(response, body.message) : body.message
    throw new ApiError(body.code, message, response.status)
  }
  if (body.data === null) {
    throw new ApiError(-1, '响应缺少 data 字段', response.status)
  }
  return body.data
}

export const api = {
  health: (signal?: AbortSignal): Promise<HealthData> => request('/health', { signal }),
  meta: (signal?: AbortSignal): Promise<MetaData> => request('/api/v1/meta', { signal }),

  login: (phone: string, password: string): Promise<TokenData> =>
    request('/api/v1/auth/login', {
      method: 'POST',
      body: JSON.stringify({ phone, password }),
    }),
  me: (signal?: AbortSignal): Promise<{ id: number; phone: string; nickname: string }> =>
    request('/api/v1/auth/me', { signal }),

  listSessions: (signal?: AbortSignal): Promise<{ items: SessionSummary[]; page: PageMeta }> =>
    request('/api/v1/sessions?limit=50', { signal }),
  createSession: (title?: string): Promise<SessionSummary> =>
    request('/api/v1/sessions', {
      method: 'POST',
      body: JSON.stringify({ title: title ?? null }),
    }),
  renameSession: (id: string, title: string): Promise<SessionSummary> =>
    request(`/api/v1/sessions/${id}`, { method: 'PATCH', body: JSON.stringify({ title }) }),
  deleteSession: (id: string): Promise<null> =>
    request(`/api/v1/sessions/${id}`, { method: 'DELETE' }),

  listMessages: (
    sessionId: string,
    beforeId?: number,
  ): Promise<{ items: MessageDto[]; page: PageMeta }> =>
    request(
      `/api/v1/sessions/${sessionId}/messages?limit=50${beforeId ? `&beforeId=${beforeId}` : ''}`,
    ),
}

/**
 * 流式对话。返回原始 Response 交给 `lib/sse.ts` 解帧——
 * 这里不解析内容，只负责把 HTTP 层错误转成 ApiError（SSE 一旦开流就不能改状态码）。
 */
export async function streamChat(
  payload: { sessionId: string; message: string; clientMsgId: string },
  signal?: AbortSignal,
): Promise<Response> {
  const headers = new Headers({ 'Content-Type': 'application/json', Accept: 'text/event-stream' })
  const token = getToken()
  if (token !== null) headers.set('Authorization', `Bearer ${token}`)

  const response = await fetch('/api/v1/chat/stream', {
    method: 'POST',
    headers,
    body: JSON.stringify(payload),
    signal,
  })

  if (!response.ok) {
    // 开流前的失败是普通 envelope，这里是前端唯一需要读 JSON 错误的地方
    const body = (await response.json().catch(() => null)) as ApiResponse<unknown> | null
    const fallback = body?.message ?? `请求失败（HTTP ${response.status}）`
    throw new ApiError(
      body?.code ?? -1,
      response.status === 429 ? rateLimitMessage(response, fallback) : fallback,
      response.status,
    )
  }
  return response
}

/**
 * 唯一网络出口（agent.md §4）：组件禁止直接 fetch。
 * 职责：拼 baseURL、带 token、解 envelope、统一抛 ApiError。
 */

import type { ApiResponse, HealthData, MetaData } from '@/types/api'

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
    throw new ApiError(body.code, body.message, response.status)
  }
  if (body.data === null) {
    throw new ApiError(-1, '响应缺少 data 字段', response.status)
  }
  return body.data
}

export const api = {
  health: (signal?: AbortSignal): Promise<HealthData> => request('/health', { signal }),
  meta: (signal?: AbortSignal): Promise<MetaData> => request('/api/v1/meta', { signal }),
}

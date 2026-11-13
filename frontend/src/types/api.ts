/**
 * 与 docs/api.md 对齐的接口类型。
 * 约定：后端金额一律整数分（字段名带 Cents），时间一律 ISO 8601 UTC 字符串。
 */

export interface ApiResponse<T> {
  code: number
  message: string
  data: T | null
  traceId: string
}

export interface PageMeta {
  nextCursor: string | null
  hasMore: boolean
  total: number | null
}

export interface HealthData {
  status: 'ok' | 'degraded'
  db: string
  vector: string
  vectorVersion: string | null
  version: string
  env: string
}

export interface MetaData {
  name: string
  version: string
  apiPrefix: string
  env: string
}

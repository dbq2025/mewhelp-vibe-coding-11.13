import { computed, onScopeDispose, ref } from 'vue'

import { ApiError, api } from '@/lib/api'
import type { HealthData } from '@/types/api'

export type HealthStatus = 'checking' | 'ok' | 'degraded' | 'offline'

const LABELS: Record<HealthStatus, string> = {
  checking: '检测中',
  ok: '服务正常',
  degraded: '服务降级',
  offline: '服务不可用',
}

/**
 * 后端健康探测：P0 用来证明前后端与数据库真的连通（不是"页面能打开"就算完）。
 * AbortController 必须在 onScopeDispose 里中断，否则切换页面会漏请求（agent.md §4）。
 */
export function useHealth() {
  const status = ref<HealthStatus>('checking')
  const detail = ref<HealthData | null>(null)
  const controller = new AbortController()

  const label = computed(() => LABELS[status.value])
  const tone = computed<'ok' | 'warn' | 'danger'>(() => {
    if (status.value === 'ok') return 'ok'
    if (status.value === 'checking') return 'warn'
    if (status.value === 'degraded') return 'warn'
    return 'danger'
  })

  async function check(): Promise<void> {
    status.value = 'checking'
    try {
      const data = await api.health(controller.signal)
      detail.value = data
      status.value = data.status === 'ok' ? 'ok' : 'degraded'
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') return
      detail.value = null
      status.value = 'offline'
      if (error instanceof ApiError) {
        console.warn('[health]', error.code, error.message)
      }
    }
  }

  onScopeDispose(() => controller.abort())

  return { status, detail, label, tone, check }
}

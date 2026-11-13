/**
 * SSE 解析（agent.md §4）：解析逻辑只在这里，组件与 store 都不碰字节流。
 *
 * 为什么不用 EventSource：对话要 POST 带 body 和 Authorization 头，EventSource 只支持 GET。
 * 所以用 fetch + ReadableStream 自己按 `\n\n` 切帧。
 */

export interface SseEvent {
  event: string
  data: Record<string, unknown>
}

export class SseParseError extends Error {}

/** 把一段 SSE 原始文本切成事件；跨 chunk 的半帧由调用方用 buffer 处理。 */
export function parseSseChunk(chunk: string): SseEvent[] {
  const events: SseEvent[] = []
  for (const block of chunk.split('\n\n')) {
    const text = block.trim()
    if (!text) continue
    let event = 'message'
    const dataLines: string[] = []
    for (const line of text.split('\n')) {
      if (line.startsWith('event:')) {
        event = line.slice(6).trim()
      } else if (line.startsWith('data:')) {
        dataLines.push(line.slice(5).trim())
      }
      // 以 ":" 开头的是注释/心跳，直接忽略
    }
    if (dataLines.length === 0) continue
    const raw = dataLines.join('\n')
    try {
      events.push({ event, data: JSON.parse(raw) as Record<string, unknown> })
    } catch {
      throw new SseParseError(`SSE 数据不是合法 JSON：${raw.slice(0, 80)}`)
    }
  }
  return events
}

/** 逐事件读取响应流。调用方负责在中途取消（AbortController）。 */
export async function* readSse(
  response: Response,
  signal?: AbortSignal,
): AsyncGenerator<SseEvent> {
  if (response.body === null) {
    throw new SseParseError('响应没有可读流')
  }
  const reader = response.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''
  try {
    while (true) {
      if (signal?.aborted) return
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const cut = buffer.lastIndexOf('\n\n')
      if (cut === -1) continue
      const complete = buffer.slice(0, cut + 2)
      buffer = buffer.slice(cut + 2)
      for (const event of parseSseChunk(complete)) {
        yield event
      }
    }
    buffer += decoder.decode()
    if (buffer.trim()) {
      for (const event of parseSseChunk(buffer)) {
        yield event
      }
    }
  } finally {
    reader.releaseLock()
  }
}
